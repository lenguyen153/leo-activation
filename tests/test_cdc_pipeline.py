"""
CDC Pipeline Diagnostic Script
Run: python tests/test_cdc_pipeline.py

Tests each stage of the real-time pipeline and reports what's working/broken.
"""

import json
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)


def header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def ok(msg):
    print(f"  [OK] {msg}")


def fail(msg):
    print(f"  [FAIL] {msg}")


def info(msg):
    print(f"  [INFO] {msg}")


# =============================================================
# TEST 1: ArangoDB Connection
# =============================================================
def test_arango_connection():
    header("1. ArangoDB Connection")
    try:
        from data_utils.settings import DatabaseSettings
        settings = DatabaseSettings()
        info(f"Host: {settings.ARANGO_HOST}")
        info(f"DB: {settings.ARANGO_DB}")
        info(f"User: {settings.ARANGO_USER}")

        db = settings.get_arango_db()
        ok(f"Connected to database: {db.name}")
        return db
    except Exception as e:
        fail(f"Cannot connect to ArangoDB: {e}")
        return None


# =============================================================
# TEST 2: ArangoDB WAL API (Replication)
# =============================================================
def test_wal_api():
    header("2. ArangoDB WAL Replication API")
    try:
        import requests
        # Use ARANGO_RAW_HOST for direct ArangoDB access (bypasses CDP proxy)
        raw_host = os.getenv("ARANGO_RAW_HOST", os.getenv("ARANGO_HOST", "http://localhost:8529"))
        raw_port = os.getenv("ARANGO_RAW_PORT", "8529")
        arango_db = os.getenv("ARANGO_DB", "leo_cdp_source")
        user = os.getenv("ARANGO_USER", "root")
        password = os.getenv("ARANGO_PASSWORD", "")

        # Build base URL with /_db/{db_name}/ prefix
        from urllib.parse import urlparse
        parsed = urlparse(raw_host.rstrip("/"))
        host = raw_host.rstrip("/") if parsed.port else f"{raw_host.rstrip('/')}:{raw_port}"
        base_url = f"{host}/_db/{arango_db}"

        info(f"Raw Host: {raw_host}")
        info(f"Raw Port: {raw_port}")
        info(f"Database: {arango_db}")
        info(f"User: {user}")
        info(f"Base URL: {base_url}")

        # Test logger-state
        url = f"{base_url}/_api/replication/logger-state"
        info(f"GET {url}")
        resp = requests.get(url, auth=(user, password), timeout=10)
        info(f"Status: {resp.status_code}")

        if resp.status_code != 200:
            fail(f"WAL API returned {resp.status_code}: {resp.text[:200]}")
            return None

        data = resp.json()
        info(f"Response keys: {list(data.keys())}")

        # Find the tick
        if "state" in data and "lastLogTick" in data["state"]:
            tick = int(data["state"]["lastLogTick"])
        elif "lastLogTick" in data:
            tick = int(data["lastLogTick"])
        elif "tick" in data:
            tick = int(data["tick"])
        else:
            fail(f"Cannot find tick in response: {json.dumps(data, indent=2)[:500]}")
            return None

        ok(f"Current WAL tick: {tick}")

        # Test logger-follow
        follow_url = f"{base_url}/_api/replication/logger-follow?from={tick}&chunkSize=65536"
        info(f"GET {follow_url}")
        resp2 = requests.get(follow_url, auth=(user, password), timeout=10)
        info(f"Status: {resp2.status_code}")

        if resp2.status_code == 204:
            ok("No new WAL entries (expected if no recent writes)")
        elif resp2.status_code == 200:
            lines = [l for l in resp2.text.strip().split("\n") if l.strip()]
            ok(f"WAL has {len(lines)} entries")
        else:
            fail(f"logger-follow returned {resp2.status_code}: {resp2.text[:200]}")

        return tick
    except Exception as e:
        fail(f"WAL API test failed: {e}")
        return None


# =============================================================
# TEST 3: Recent Tracking Events in ArangoDB
# =============================================================
def test_recent_events(db):
    header("3. Recent cdp_trackingevent Documents")
    if not db:
        fail("Skipped — no ArangoDB connection")
        return

    try:
        cursor = db.aql.execute("""
            FOR e IN cdp_trackingevent
                SORT e.createdAt DESC
                LIMIT 10
                RETURN {
                    key: e._key,
                    metric: e.metricName,
                    fingerprint: e.fingerprintId,
                    instrument_id: e.eventData.instrument_id,
                    instrument_id_list: e.eventData.instrument_id_list,
                    created: e.createdAt
                }
        """)
        events = list(cursor)

        if not events:
            fail("No events found in cdp_trackingevent")
            return

        ok(f"Found {len(events)} recent events")

        cdc_eligible = 0
        for e in events:
            has_ticker = bool(e.get("instrument_id")) or bool(e.get("instrument_id_list"))
            has_fp = bool(e.get("fingerprint"))
            status = "ELIGIBLE" if (has_ticker and has_fp) else "FILTERED OUT"
            if has_ticker and has_fp:
                cdc_eligible += 1

            print(f"    [{status}] key={e['key']} metric={e['metric']} "
                  f"ticker={e.get('instrument_id') or e.get('instrument_id_list')} "
                  f"fp={e.get('fingerprint', 'MISSING')} "
                  f"created={e['created']}")

        if cdc_eligible == 0:
            fail("No events have instrument_id — CDC poller will skip all of them")
            info("The app must set eventData.instrument_id or eventData.instrument_id_list")
        else:
            ok(f"{cdc_eligible}/{len(events)} events are CDC-eligible")

    except Exception as e:
        fail(f"Query failed: {e}")


# =============================================================
# TEST 4: Event Metrics (Score Lookup)
# =============================================================
def test_event_metrics(db):
    header("4. cdp_eventmetric Collection (Score Mapping)")
    if not db:
        fail("Skipped — no ArangoDB connection")
        return

    try:
        cursor = db.aql.execute("""
            FOR m IN cdp_eventmetric
                RETURN { name: m.eventName, score: m.score }
        """)
        metrics = list(cursor)

        if not metrics:
            fail("No metrics found in cdp_eventmetric — all events will get score 0.0")
            return

        ok(f"Found {len(metrics)} metric definitions")
        for m in metrics:
            print(f"    {m['name']:30s} → score: {m['score']}")

    except Exception as e:
        fail(f"Query failed: {e}")


# =============================================================
# TEST 5: Redis Connectivity (DB 2)
# =============================================================
def test_redis():
    header("5. Redis DB 2 (CDC State)")
    try:
        import redis
        # CDC pipeline always uses Redis DB 2
        redis_url = os.getenv("CDC_REDIS_URL", "redis://localhost:6379/2")
        info(f"URL: {redis_url}")

        r = redis.from_url(redis_url, decode_responses=True)
        r.ping()
        ok("Redis connected")

        # Check tick
        tick = r.get("cdc:arango:last_tick")
        info(f"cdc:arango:last_tick = {tick or '(not set)'}")

        # Check leader
        leader = r.get("cdc:poller:leader")
        info(f"cdc:poller:leader = {leader or '(not set — poller can acquire)'}")

        # Check fingerprint cache
        fp_keys = r.keys("fp:*")
        info(f"Fingerprint cache entries: {len(fp_keys)}")
        if fp_keys:
            sample = fp_keys[:3]
            for k in sample:
                print(f"    {k} → {r.get(k)}")
        else:
            fail("Fingerprint cache is empty — run profile sync first")
            info("docker-compose exec celery-worker python -c \"from data_workers.tasks import sync_profiles_task; sync_profiles_task(segment_name='Active in last 3 months')\"")

        # Check throttle keys
        throttle_keys = r.keys("nba_throttle:*")
        info(f"NBA throttle keys: {len(throttle_keys)}")

        return r
    except Exception as e:
        fail(f"Redis connection failed: {e}")
        return None


# =============================================================
# TEST 6: PostgreSQL Connection
# =============================================================
def test_postgres():
    header("6. PostgreSQL Connection")
    try:
        from data_utils.settings import DatabaseSettings
        settings = DatabaseSettings()
        conn = settings.get_pg_connection()

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) as cnt FROM product_recommendations")
            row = cur.fetchone()
            count = row["cnt"] if isinstance(row, dict) else row[0]
            ok(f"Connected — {count} rows in product_recommendations")

            cur.execute("""
                SELECT product_id, interest_score, next_best_action, updated_at
                FROM product_recommendations
                ORDER BY updated_at DESC
                LIMIT 5
            """)
            rows = cur.fetchall()
            if rows:
                info("Most recently updated scores:")
                for r in rows:
                    if isinstance(r, dict):
                        print(f"    ticker={r['product_id']} score={r['interest_score']} "
                              f"nba={r['next_best_action']} updated={r['updated_at']}")
                    else:
                        print(f"    {r}")

        conn.close()
        return True
    except Exception as e:
        fail(f"PG connection failed: {e}")
        return False


# =============================================================
# TEST 7: CDC Filter Simulation
# =============================================================
def test_filter_simulation(db):
    header("7. CDC Filter Simulation (would the poller catch these?)")
    if not db:
        fail("Skipped — no ArangoDB connection")
        return

    try:
        from services.cdc_poller.filters import should_publish

        # Simulate WAL entries from recent events
        cursor = db.aql.execute("""
            FOR e IN cdp_trackingevent
                SORT e.createdAt DESC
                LIMIT 5
                RETURN e
        """)

        for event in cursor:
            # Simulate a WAL entry structure
            fake_wal = {
                "type": 2300,
                "cname": "cdp_trackingevent",
                "data": event,
            }
            result = should_publish(fake_wal)
            ticker = event.get("eventData", {}).get("instrument_id") or event.get("eventData", {}).get("instrument_id_list")
            print(f"    {'PASS' if result else 'SKIP'} | metric={event.get('metricName')} "
                  f"ticker={ticker} fp={event.get('fingerprintId', 'NONE')}")

    except Exception as e:
        fail(f"Simulation failed: {e}")


# =============================================================
# TEST 8: Kafka Connectivity
# =============================================================
def test_kafka():
    header("8. Kafka Connectivity")
    try:
        from confluent_kafka.admin import AdminClient
        bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        info(f"Bootstrap: {bootstrap}")

        admin = AdminClient({"bootstrap.servers": bootstrap})
        metadata = admin.list_topics(timeout=5)

        topics = list(metadata.topics.keys())
        ok(f"Connected — {len(topics)} topics")

        cdc_topics = ["cdp.events.raw", "leo.score.updates", "leo.nba.actions", "leo.dlq"]
        for t in cdc_topics:
            status = "EXISTS" if t in topics else "MISSING (will auto-create on first produce)"
            print(f"    {t}: {status}")

        return True
    except ImportError:
        info("confluent_kafka not installed locally — checking Kafka via Docker instead")
        import subprocess
        try:
            result = subprocess.run(
                ["docker", "exec", "my_kafka",
                 "kafka-topics", "--bootstrap-server", "localhost:9092", "--list"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                topics = [t for t in result.stdout.strip().split("\n") if t.strip()]
                ok(f"Kafka reachable via Docker — {len(topics)} topics")
                cdc_topics = ["cdp.events.raw", "leo.score.updates", "leo.nba.actions", "leo.dlq"]
                for t in cdc_topics:
                    status = "EXISTS" if t in topics else "MISSING (will auto-create on first produce)"
                    print(f"    {t}: {status}")
                return True
            else:
                fail(f"Kafka container returned error: {result.stderr[:200]}")
                return False
        except Exception as e2:
            fail(f"Cannot reach Kafka locally or via Docker: {e2}")
            info("Is Kafka running? docker-compose up -d kafka")
            return False
    except Exception as e:
        fail(f"Kafka connection failed: {e}")
        info("Is Kafka running? docker-compose up -d kafka")
        return False


# =============================================================
# TEST 9: End-to-End Insert + Watch
# =============================================================
def test_end_to_end(db):
    header("9. End-to-End: WAL Tail — Check for Recent CDC-Eligible Events")
    info("This test reads the WAL (read-only) to verify the poller would see events.")
    info("To trigger events: browse stocks in the app (ticker-view, stock-search, etc.)")

    try:
        import requests

        # Use raw host for WAL API
        raw_host = os.getenv("ARANGO_RAW_HOST", os.getenv("ARANGO_HOST", "http://localhost:8529"))
        raw_port = os.getenv("ARANGO_RAW_PORT", "8529")
        arango_db = os.getenv("ARANGO_DB", "leo_cdp_source")
        user = os.getenv("ARANGO_USER", "root")
        password = os.getenv("ARANGO_PASSWORD", "")

        from urllib.parse import urlparse
        parsed = urlparse(raw_host.rstrip("/"))
        e2e_host = raw_host.rstrip("/") if parsed.port else f"{raw_host.rstrip('/')}:{raw_port}"
        e2e_base = f"{e2e_host}/_db/{arango_db}"

        # Get current WAL tick
        state_url = f"{e2e_base}/_api/replication/logger-state"
        info(f"GET {state_url}")
        state_resp = requests.get(state_url, auth=(user, password), timeout=10)
        if state_resp.status_code != 200:
            fail(f"logger-state returned {state_resp.status_code}: {state_resp.text[:200]}")
            return

        state_data = state_resp.json()
        if "state" in state_data and "lastLogTick" in state_data["state"]:
            head_tick = int(state_data["state"]["lastLogTick"])
        elif "lastLogTick" in state_data:
            head_tick = int(state_data["lastLogTick"])
        else:
            head_tick = 0
        info(f"WAL head tick: {head_tick}")

        # Read recent WAL entries (last ~64KB)
        from_tick = max(head_tick - 10000, 0)
        follow_url = f"{e2e_base}/_api/replication/logger-follow?from={from_tick}&chunkSize=65536"
        info(f"GET {follow_url}")
        resp = requests.get(follow_url, auth=(user, password), timeout=10)

        if resp.status_code == 204:
            info("No WAL entries in range — database is idle")
            info("Browse a stock in the app, then re-run this test")
            return

        if resp.status_code != 200:
            fail(f"logger-follow returned {resp.status_code}: {resp.text[:200]}")
            return

        lines = [l for l in resp.text.strip().split("\n") if l.strip()]
        info(f"Total WAL entries in range: {len(lines)}")

        # Look for CDC-eligible tracking events
        cdc_eligible = []
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if (entry.get("type") == 2300
                    and entry.get("cname") == "cdp_trackingevent"):
                data = entry.get("data", {})
                ed = data.get("eventData", {})
                ticker = ed.get("instrument_id") or ed.get("instrument_id_list")
                fp = data.get("fingerprintId")
                metric = data.get("metricName")

                if ticker and fp:
                    cdc_eligible.append({
                        "key": data.get("_key"),
                        "metric": metric,
                        "ticker": ticker,
                        "fp": fp,
                        "created": data.get("createdAt", "?"),
                    })

        if cdc_eligible:
            ok(f"Found {len(cdc_eligible)} CDC-eligible events in WAL")
            for e in cdc_eligible[:10]:
                print(f"    key={e['key']} metric={e['metric']} "
                      f"ticker={e['ticker']} fp={e['fp'][:16]}... "
                      f"created={e['created']}")
        else:
            info("No CDC-eligible events in recent WAL entries")
            info("CDC-eligible = cdp_trackingevent with instrument_id + fingerprintId")
            info("Browse a stock in the app to generate ticker-view events, then re-run")

    except Exception as e:
        fail(f"End-to-end test failed: {e}")


# =============================================================
# MAIN
# =============================================================
if __name__ == "__main__":
    print("\n  CDC Pipeline Diagnostic Script")
    print("  ================================\n")

    db = test_arango_connection()
    test_wal_api()
    test_recent_events(db)
    test_event_metrics(db)
    test_redis()
    test_postgres()
    test_filter_simulation(db)
    test_kafka()
    test_end_to_end(db)

    header("DONE")
    print("  Check [FAIL] items above to identify the issue.\n")
