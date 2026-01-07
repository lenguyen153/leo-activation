
# LEO Activation – Database Schema Documentation

**AI-Driven Marketing Activation Platform**
**Database:** PostgreSQL 15+ / 16
**Scope:** Core Activation – Strategy → Decision → Execution
**Status:** Production-ready

---

## 1. Mục tiêu của schema này

Schema này **không phải** chỉ để “gửi email / push”.

Nó được thiết kế để:

* Kích hoạt marketing **theo sự kiện (event-driven)**
* Có **Agent (AI / Rule)** ra quyết định
* Ghi nhận **ai – vì sao – gửi gì – cho ai – kết quả ra sao**
* Đảm bảo:

  * Deterministic (cùng input → cùng output)
  * Observable (trace được toàn bộ flow)
  * Auditable (audit, attribution, compliance)

> Nếu không trace được → không phải Activation system.

---

## 2. Nguyên tắc thiết kế cốt lõi

### 2.1 Multi-tenancy tuyệt đối

* Mọi bảng đều có `tenant_id`
* **Row Level Security (RLS)** bật ở DB level
* Không tin application layer một mình

```sql
SET app.current_tenant_id = '<tenant-uuid>';
```

Không set → query trả về **0 row**.

---

### 2.2 Tách rõ 4 lớp

| Lớp             | Bảng              |
| --------------- | ----------------- |
| Strategy        | `campaign`        |
| Definition      | `marketing_event` |
| Decision        | `agent_task`      |
| Execution Truth | `delivery_log`    |

Segment là **dữ liệu động**, nên phải snapshot.

---

## 3. Tổng quan data model

```
tenant
 ├── cdp_profiles
 │    └── segment_snapshots (denormalized)
 │
 ├── campaign
 │    └── marketing_event
 │         ├── agent_task
 │         └── delivery_log
 │
 └── segment_snapshot
      └── segment_snapshot_member
```

---

## 4. Giải thích chi tiết từng bảng

---

### 4.1 `tenant`

**Ý nghĩa:** ranh giới bảo mật cao nhất (company / workspace)

| Field       | Mô tả                 |
| ----------- | --------------------- |
| tenant_id   | UUID định danh tenant |
| tenant_name | Tên tenant            |
| status      | active / disabled     |
| created_at  | Thời điểm tạo         |
| updated_at  | Thời điểm update      |

---

### 4.2 `cdp_profiles`

**Ý nghĩa:** hồ sơ khách hàng hợp nhất (CDP)

| Field             | Mô tả                               |
| ----------------- | ----------------------------------- |
| profile_id        | ID nội bộ                           |
| ext_id            | ID từ CRM / ERP                     |
| email             | Email (citext)                      |
| mobile_number     | SĐT                                 |
| segments          | Segment **hiện tại** (dynamic)      |
| data_labels       | Nhãn phân loại                      |
| segment_snapshots | Danh sách snapshot ID đã từng thuộc |
| raw_attributes    | Dữ liệu linh hoạt                   |

⚠️ `segment_snapshots`:

* **Denormalized**
* **Append-only**
* Chỉ dùng để lookup nhanh
* Source of truth là `segment_snapshot_member`

---

### 4.3 `campaign`

**Ý nghĩa:** chiến lược marketing (WHY)

| Field             | Mô tả                       |
| ----------------- | --------------------------- |
| campaign_id       | ID campaign                 |
| campaign_code     | Code business               |
| campaign_name     | Tên chiến dịch              |
| objective         | Mục tiêu                    |
| status            | active / paused / completed |
| start_at / end_at | Thời gian hiệu lực          |

👉 Campaign **không gửi gì cả**.
Nó chỉ định nghĩa **ý đồ**.

---

### 4.4 `marketing_event`

**Ý nghĩa:** đơn vị thực thi (WHAT)

Ví dụ:

* Email blast
* Webinar
* Push notification
* Zalo OA message

| Field             | Mô tả                        |
| ----------------- | ---------------------------- |
| event_id          | Deterministic hash           |
| campaign_id       | Campaign cha                 |
| event_name        | Tên event                    |
| event_type        | email / webinar / push       |
| event_channel     | channel cụ thể               |
| start_at / end_at | Thời gian                    |
| embedding         | Vector cho AI                |
| status            | planned / active / cancelled |

Đặc điểm:

* Partition theo `tenant_id`
* `event_id` sinh **deterministic** (idempotent)

---

### 4.5 `segment_snapshot`

**Ý nghĩa:** snapshot **bất biến** của audience tại thời điểm kích hoạt

| Field           | Mô tả           |
| --------------- | --------------- |
| snapshot_id     | ID snapshot     |
| segment_name    | Tên segment     |
| segment_version | Hash / version  |
| snapshot_reason | Vì sao snapshot |
| created_at      | Thời điểm tạo   |

📌 Snapshot **không chứa profile_id**.

---

### 4.6 `segment_snapshot_member`

**Ý nghĩa:** mapping snapshot → profile (scale-safe)

| Field       | Mô tả                  |
| ----------- | ---------------------- |
| snapshot_id | Snapshot               |
| profile_id  | Profile thuộc snapshot |
| created_at  | Thời điểm ghi nhận     |

✔ Thiết kế này:

* Chịu được 100K–1M profiles
* Không dùng array / JSON to
* Audit & attribution chuẩn

---

### 4.7 `agent_task`

**Ý nghĩa:** dấu vết quyết định của Agent (AI / Rule)

| Field             | Mô tả                        |
| ----------------- | ---------------------------- |
| task_id           | ID task                      |
| agent_name        | Tên agent                    |
| task_type         | plan / execute / evaluate    |
| campaign_id       | Context                      |
| event_id          | Context                      |
| snapshot_id       | Audience snapshot            |
| reasoning_summary | Lý do (text)                 |
| reasoning_trace   | Chi tiết (JSON)              |
| status            | pending / completed / failed |

📌 Đây là **flight recorder** cho AI.

Không có bảng này → AI = black box.

---

### 4.8 `delivery_log`

**Ý nghĩa:** sự thật duy nhất về việc gửi (EXECUTION TRUTH)

| Field             | Mô tả                     |
| ----------------- | ------------------------- |
| delivery_id       | ID                        |
| event_id          | Event                     |
| profile_id        | Người nhận                |
| snapshot_id       | Snapshot lúc gửi          |
| channel           | email / zalo / push       |
| destination       | Email / phone             |
| delivery_status   | sent / delivered / failed |
| provider_response | Response từ provider      |
| sent_at           | Thời điểm gửi             |

📌 **delivery_log không bao giờ bị rewrite**.
Sai → ghi row mới.

---

## 5. Vì sao schema này đúng cho LEO Activation

* Không “segment drift”
* Không mất lịch sử
* Không AI mù mờ
* Không attribution giả
* Không cross-tenant leak

Nó buộc hệ thống phải **trung thực với thời gian**.

---

## 6. Nguyên tắc vàng

> Campaign nói **vì sao**
> Event nói **gửi cái gì**
> Snapshot nói **gửi cho ai lúc đó**
> Agent nói **ai quyết định**
> Delivery log nói **thực sự đã xảy ra gì**

Nếu một hệ Activation không trả lời được đủ 5 câu trên → **không đáng tin**.

---

## 7. Phạm vi KHÔNG xử lý ở schema này

* Authentication / User
* UI / Dashboard
* Channel provider config
* Raw clickstream

Schema này là **xương sống**, không phải toàn bộ cơ thể.

---

### Kết luận

Đây là schema dành cho:

* hệ activation **có AI**
* hệ cần audit
* hệ cần scale
* hệ không chấp nhận “gửi nhầm là xong”

Nếu bạn cần:

* migration guide
* sample queries
* attribution SQL
* load test checklist

→ nói tiếp, chúng ta đang ở đúng tầng kiến trúc.
