# System Architecture: 1invest Social Platform Foundation

## Assumptions

- Tài liệu này mô tả kiến trúc hệ thống mức tổng thể cho MVP, không phải thiết kế triển khai chi tiết từng endpoint.
- Phạm vi bám theo `spec.md` và `plan.md` của feature `001-social-platform-foundation`.
- Giữ nguyên các ràng buộc đã chốt trong spec: Flutter mobile client, Keycloak là identity authority, FastAPI BFF là điểm vào duy nhất, OSSN là social core, social writes xử lý bất đồng bộ.

## System Goal

Xây dựng nền tảng social feed cho 1invest theo mô hình mobile-first, cho phép:

- Đăng nhập một lần bằng tài khoản 1invest.
- Tự động đồng bộ hoặc tạo social profile cho người dùng.
- Đọc bảng tin nhanh, hỗ trợ cuộn liên tục.
- Đăng bài và like với phản hồi tức thì trên giao diện.
- Ghi nhận dữ liệu nền theo hướng eventual consistency.

## High-Level Architecture

```text
[ Mobile App (Flutter) ]
        |
        | OIDC login + API calls
        v
[ Keycloak ] <---- identity authority ----> [ 1invest user identity source / user master ]
        |
        | access token / id token
        v
[ FastAPI BFF ]
   |        |         |
   |        |         +--> [ Redis ]       (feed cache, counters, temp reconciliation state)
   |        |
   |        +--> [ RabbitMQ ] ---> [ Workers/Celery ]
   |                                  |
   |                                  v
   +-------------------------------> [ OSSN ]
                                        |
                                        v
                                 [ MySQL/MariaDB ]
```

## Core Components

### 1. Flutter Mobile App

Ứng dụng Flutter là client chính trong MVP và chịu trách nhiệm:

- Thực hiện đăng nhập qua chuẩn OIDC.
- Lưu token an toàn trên thiết bị.
- Gọi API qua FastAPI BFF.
- Hiển thị feed, infinite scroll, create post, like.
- Áp dụng optimistic UI cho các thao tác ghi.

### 2. Keycloak

Keycloak là hệ thống xác thực tập trung và là identity authority của toàn hệ thống.

Trách nhiệm chính:

- Xử lý đăng nhập một lần.
- Phát hành access token và ID token.
- Quản lý phiên và thông tin định danh người dùng.
- Cung cấp branded authentication UI qua theme.

### 3. FastAPI BFF

FastAPI BFF là cổng duy nhất giữa mobile app và social platform.

Trách nhiệm chính:

- Xác thực token từ Keycloak.
- Ánh xạ identity người dùng sang social profile.
- Trigger provisioning profile trong OSSN khi cần.
- Cung cấp API đọc feed cho mobile.
- Nhận yêu cầu create post và like.
- Publish async jobs sang hàng đợi.
- Chuẩn hóa response contract độc lập với OSSN internals.

### 4. Redis

Redis phục vụ cho read optimization và dữ liệu tạm thời.

Vai trò chính:

- Cache feed pages.
- Cache counters hoặc derived read state nếu cần.
- Hỗ trợ giảm tải cho OSSN ở luồng đọc.
- Hỗ trợ quá trình reconcile optimistic state ở mức ngắn hạn nếu cần.

Redis không phải source-of-truth.

### 5. RabbitMQ

RabbitMQ là lớp vận chuyển message cho các tác vụ bất đồng bộ.

Vai trò chính:

- Nhận job từ BFF cho create post.
- Nhận job từ BFF cho like hoặc unlike.
- Tách read path khỏi write path để tối ưu trải nghiệm người dùng.

### 6. Workers/Celery

Workers xử lý các social write operations ở nền.

Vai trò chính:

- Đọc job từ RabbitMQ.
- Ghi post hoặc like vào OSSN.
- Retry các tác vụ lỗi ở mức cơ bản.
- Invalidate hoặc refresh cache liên quan sau khi write thành công.
- Đảm bảo eventual consistency giữa phản hồi tức thì ở app và trạng thái cuối trong social core.

### 7. OSSN

OSSN là social engine và là nơi chứa nghiệp vụ social cốt lõi của MVP.

Vai trò chính:

- Quản lý hồ sơ social profile.
- Lưu bài viết.
- Lưu trạng thái like.
- Cung cấp dữ liệu social gốc cho feed read path.

### 8. MySQL/MariaDB

MySQL/MariaDB là database nguồn sự thật cho dữ liệu OSSN.

Lưu trữ chính:

- Hồ sơ social.
- Bài viết.
- Tương tác like.
- Dữ liệu nền tảng của OSSN.

## Architecture Boundaries

Các boundary bắt buộc của hệ thống:

- Flutter app chỉ gọi FastAPI BFF.
- Flutter app không truy cập trực tiếp OSSN.
- Không dùng OSSN UI qua WebView trong mobile app.
- Keycloak là nguồn xác thực duy nhất.
- Social writes như create post và like được xử lý bất đồng bộ theo mặc định.
- OSSN là social source-of-truth, còn Redis chỉ là lớp tăng tốc đọc.

## Main Business Flows

### 1. Login and Social Access

Luồng chính:

1. Mobile app mở đăng nhập qua Keycloak.
2. Người dùng xác thực thành công.
3. App nhận token hợp lệ.
4. App gọi BFF bằng token đó.
5. BFF verify token và xác định user context.
6. Nếu social profile chưa tồn tại, BFF tạo mới hoặc kích hoạt provisioning flow vào OSSN.
7. Người dùng được phép truy cập feed.

Kết quả mong muốn:

- Người dùng chỉ đăng nhập một lần.
- Không cần đăng ký thêm tài khoản social riêng.
- Social profile luôn tồn tại hoặc được tạo tự động khi cần.

### 2. Feed Read

Luồng chính:

1. App gọi endpoint feed tại BFF.
2. BFF kiểm tra cache trong Redis.
3. Nếu cache hit, trả dữ liệu ngay.
4. Nếu cache miss, BFF lấy dữ liệu từ OSSN.
5. BFF chuẩn hóa response theo mobile contract.
6. BFF cache dữ liệu phù hợp trong Redis.
7. App render feed và tiếp tục dùng cursor để tải thêm.

Kết quả mong muốn:

- Feed hiển thị nhanh.
- Infinite scroll hoạt động liên tục.
- Không trả lặp dữ liệu đã xem.

### 3. Create Post

Luồng chính:

1. App gửi yêu cầu tạo bài viết đến BFF.
2. BFF validate và chấp nhận nhanh.
3. App hiển thị optimistic post ngay trên đầu feed.
4. BFF publish job create-post sang RabbitMQ.
5. Worker xử lý job và ghi bài viết vào OSSN.
6. Worker invalidates hoặc refresh cache feed liên quan.
7. Trạng thái cuối được phản ánh ở các lần đọc feed tiếp theo.

Kết quả mong muốn:

- Người dùng nhận phản hồi tức thì.
- Hệ thống nền hoàn tất ghi nhận sau đó.
- Feed cuối cùng nhất quán với dữ liệu OSSN.

### 4. Like Post

Luồng chính:

1. App gửi yêu cầu like hoặc unlike đến BFF.
2. BFF xác nhận chấp nhận yêu cầu.
3. App cập nhật trạng thái like và counter ngay lập tức.
4. BFF publish job like-action sang RabbitMQ.
5. Worker cập nhật trạng thái trong OSSN.
6. Worker invalidates hoặc refresh cache liên quan.
7. Các lần đọc feed sau phản ánh trạng thái cuối cùng.

Kết quả mong muốn:

- Tương tác cảm nhận là tức thì.
- Hệ thống vẫn giữ được trạng thái cuối cùng chính xác.

## Layered Structure

### Client Layer

Bao gồm:

- Flutter UI.
- State management.
- Auth session handling.
- Feed rendering.
- Optimistic interaction state.

### API and Edge Layer

Bao gồm:

- FastAPI routes.
- Request validation.
- Token verification.
- Response shaping cho mobile app.

### Application Layer

Bao gồm:

- Provisioning logic cho social profile.
- Feed use cases.
- Cursor pagination logic.
- Async command acceptance cho post và like.
- Cache strategy orchestration.

### Async Processing Layer

Bao gồm:

- Job publishing.
- Queue consumption.
- Retry handling.
- Cache invalidation hoặc refresh sau write.

### Social Core Layer

Bao gồm:

- OSSN integration adapters.
- Social profile adapters.
- Feed data adapters.
- Post và reaction adapters.

### Infrastructure Layer

Bao gồm:

- Keycloak.
- Redis.
- RabbitMQ.
- MySQL/MariaDB.
- Docker và deployment configuration.

## Suggested Repository Structure

```text
apps/
└── flutter_app/
    ├── lib/
    │   ├── app/
    │   ├── features/
    │   │   ├── auth/
    │   │   ├── feed/
    │   │   └── post_creation/
    │   └── shared/
    └── test/

services/
├── bff/
│   ├── app/
│   │   ├── api/
│   │   ├── auth/
│   │   ├── feed/
│   │   ├── social/
│   │   ├── queue/
│   │   ├── models/
│   │   └── core/
│   └── tests/
└── workers/
    └── social_workers/
        ├── post_worker/
        └── action_worker/

infrastructure/
├── docker/
├── keycloak/
│   └── theme/
├── messaging/
└── ossn/
```

## Data Ownership

- Keycloak sở hữu identity, authentication session và token issuance.
- OSSN cùng MySQL/MariaDB sở hữu dữ liệu social cuối cùng.
- Redis sở hữu dữ liệu cache và state ngắn hạn, không phải dữ liệu nguồn.
- RabbitMQ chỉ vận chuyển job, không lưu business truth.
- BFF sở hữu API contract, orchestration và security boundary, không nên trở thành nơi lưu social data lâu dài.

## Why This Structure Fits the MVP

Kiến trúc này phù hợp với MVP vì:

- Giữ đúng boundary mà spec yêu cầu.
- Cho phép mobile app độc lập với OSSN internals.
- Tối ưu read path mà không làm phức tạp write path.
- Hỗ trợ optimistic UI tốt cho mobile experience.
- Tách rõ identity, orchestration, async processing và social core.
- Tránh thêm microservice hoặc abstraction không cần thiết ở giai đoạn đầu.

## Explicitly Out of Scope

Các phần sau không nằm trong cấu trúc MVP hiện tại:

- Notification service.
- Comment service.
- External sharing flow.
- Moderation console.
- Web client hoặc non-mobile client runtime.
- Dedicated analytics pipeline.
- Full CQRS hoặc event sourcing.
- Một database riêng cho BFF nếu chưa có nhu cầu thực tế.

## Recommended Next Documents

Nếu cần đi tiếp, nên bổ sung các tài liệu sau:

- Sequence diagram cho login, feed read, create post, và like.
- API boundary document chi tiết giữa Flutter và BFF.
- Worker processing contract cho create-post và like-action.
- Cache invalidation strategy cho feed và counters.
