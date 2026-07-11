# 계획 문서 — TJ Finance를 NAS 기반 완전 재무 서버로 이전

> **이 파일의 성격**: 사용자에게 전달할 **planning 문서** 최종본입니다(전문가 리뷰 반영 완료). 승인 시
> `docs/nas_finance_server_plan.md`로 저장. **지금 실행하지 않으며**, 사용자가 읽고 티어·전략·트리거를 결정하는 용도.

---

## 0. Context — 왜 이 문서인가

**최종 목표**: Mac에서 핵심 개발(‘V2’)까지 마친 뒤 **DB 운영·보고서 수집·파싱·DB 적재·시각화 앱**을 전부 NAS로 이전, Mac은 순수 사용자로 복귀. NAS를 24/7·집 밖 접속 가능한 “완전 재무 서버”로.

지금 실행이 아니라, **HW/SW·문제·성능·비용을 미리 파악**하고 **네 가지 배포 전략**을 비교해 결정하기 위한 계획서. 실행 전 **실험(PoC) 계획** 포함.

### 이미 끝난 선행 작업
- **raw_report(218GB) → NAS 전환 완료**(2026-07-06, 심링크 재지정). 현재 NAS가 main.
- **DB 백업 → NAS 직접 저장**(`backup_db.py --out-dir`). 최근 07-05~07-11 덤프 보관.
- **앱은 fact_v2(80GB)를 전혀 쿼리하지 않음**. 앱 워킹셋 **~3.8GB**.

---

## 1. 현재 상태 (이전 기준선)

| 항목 | Mac (현재) | NAS 목표 (DS723+) |
|---|---|---|
| 기기 | MacBook Pro **M1 Pro, 10코어(8P+2E), 16GB**, arm64 | **AMD Ryzen R1600, 2코어/4스레드**, x86-64, 18GB, DSM(Linux) |
| PostgreSQL | **15.18** (Homebrew) | **18.4** (Container Manager/Docker 권장) |
| DB | **87GB**(fact_v2 80GB, 나머지 ~7GB), 확장=plpgsql 1개, 인덱스 79, matview 1(valuation_daily 11.2M행) | 논리 이전 |
| 저장 | raw_report 218GB(~35.6만 한글파일), 백업(NAS) | 로컬 볼륨화 |

**핵심**: 확장이 plpgsql 하나뿐 → **PG 15→18 논리 이전(dump/restore) 자체는 안전**. 물리 복제는 ARM↔x86 + 15↔18로 불가 → **반드시 논리 이전**. 단, “silent-wrong” 위험(로케일/콜레이션)은 §4·§7에서 별도 관리(★리뷰 반영).

---

## 2. 목표 아키텍처 — NAS = 완전 재무 서버

역할 5개(전략별 분담): ① DB 운영(PG18, PGDATA는 빠른 SSD 볼륨) ② 수집(DART+가격, 아웃바운드 HTTPS) ③ 파싱(fin2 extract, Gate B) ④ 적재(reconcile/standardize, matview) ⑤ 시각화(Streamlit 0.0.0.0:8501 headless + 원격).

**저장 배치**: PGDATA=NVMe(빠름, 파일시스템 주의 §6), raw_report+백업=SATA HDD RAID1(대용량·이중화). 백업은 PGDATA와 **다른 물리 볼륨 + NAS 밖 1부**(3-2-1, §8).

---

## 3. HW 준비 — 3개 티어 (★리뷰로 비용·NVMe 정정)

DS723+ 실사양 반영. 비용은 개략치(₩, 2026 추정).

**DS723+ 하드 제약(검증됨)**: RAM 공식 최대 **32GB(16×2, ECC SODIMM)** — 기본 2GB 1개는 증설 시 제거. M.2 NVMe를 **볼륨**으로 쓰려면 **Synology 정품 NVMe(SNV3410/5400)** 필요(비정품은 캐시로만 인식되거나 비공식 `007revad` 스크립트 필요 → DSM 업데이트 시 깨질 수 있음, 시스템DB엔 부적합). 2코어는 **어떤 티어로도 불변**.

| 구분 | 최소 | 권장(균형) | 최대(무중단) |
|---|---|---|---|
| RAM | 18GB 유지 | **32GB(2×16 ECC)** | 32GB |
| PGDATA 저장 | NVMe **캐시**(비정품 가능) 위 HDD 볼륨 → **matview/VACUUM 느림** | **Synology 정품 NVMe 2× RAID1 볼륨**(~400~800GB, ext4 또는 CoW off, §6) | 동일 |
| 대용량 저장 | 기존 | **SATA HDD RAID1**(raw_report+백업) | HDD RAID1 |
| 전원/백업 | — | **UPS 권장(★)**, 백업 별볼륨 | UPS + **NAS 밖 백업 2차**(클라우드/외장/2nd NAS) + DX517 |
| 추가비용(개략) | ~₩5~15만 | **₩70~110만**(RAM 30~40 + 정품NVMe 2× 30~50 + UPS 10~20) | 권장 + ₩20~60만 |
| 일상(daily) 성능 | 충분(수 분) | 충분(여유) | 충분 |
| **풀백필 성능** | **8~15× 느림(★)** | **8~15× 느림(동일)** | **8~15× 느림(동일)** |
| DB 서빙/캐시 | 앱셋 3.8GB OK, 핫셋 여유 적음 | 핫셋 여유(shared_buffers 8GB) | 동일 |
| 무중단성 | 낮음(SPOF) | 중간~높음 | 높음 |

> ★ **최중요**: RAM·SSD는 **DB 서빙·I/O**만 개선. **풀백필 CPU 병목(2코어)은 어떤 티어로도 해결 불가.** 코어를 늘리는 길은 **전략 B(Mac) 또는 C/D(미니PC)** 뿐. **권장 티어 실지출 ₩70~110만은 “약한 2코어 DB 호스트”에 쓰는 비용** — 비슷하거나 적은 돈이 훨씬 강한 DB 호스트(미니PC, §5-D)를 살 수 있다는 점을 반드시 비교할 것.

---

## 4. SW 준비물 (이식성 감사 — 코드 재작성 아님, 설정/경로/스케줄러/로케일 번역)

차단 이슈 없음. 필요한 작업:

1. **컨테이너 배포**: DSM 7.2+ Container Manager, **Debian 기반 `postgres:18` 이미지**(Alpine/musl 금지). 앱/파이프라인은 컨테이너 또는 네이티브 venv.
2. **★ 로케일/콜레이션(silent-wrong 방지)**: 소스의 `lc_collate/lc_ctype`·`pg_database` 콜레이션 확보 → 컨테이너 이미지에 해당 로케일 생성(`locale-gen ko_KR.UTF-8`/`en_US.UTF-8`) 또는 **ICU 콜레이션 표준화**(플랫폼 무관 정렬) → 타깃 DB를 **같은 LC_COLLATE/LC_CTYPE로 생성** 후 restore. 안 맞으면 한글 정렬·범위·unique tie-break가 **조용히 달라짐**.
3. **venv 재생성**: Python 3.9~3.12 핀. `requirements.txt`에 **`requests` 명시 추가**.
4. **PG 클라이언트 PATH**: `pg_dump/pg_restore/psql/vacuumdb/createdb/dropdb`. `backup_db.py:37`·`vacuum_db.py:34`·`restore_drill.py:47` 폴백(`/opt/homebrew`)은 PATH 없으면 실패. **덤프는 PG18 클라이언트로**(전방호환 + `--compress=zstd`).
5. **경로 수정**: `raw_report` 심링크 → NAS 로컬 볼륨(SMB 루프백 금지); `restore_drill.py:27 BACKUP_DIR`(하드코딩) + `backup_db.py:32 DEFAULT_OUT` → NAS 로컬.
6. **스케줄러**: launchd 5개 → cron/DSM Task Scheduler(시간·순서 유지). `pmset`/wake 폐기. **컨테이너 `restart: unless-stopped`**.
7. **알림**: `notify.py` osascript(Linux서 조용히 no-op=알림 유실) → 이메일/DSM/webhook + 헬스 모니터링(디스크·컨테이너·matview 실패·PG 로그).
8. **Streamlit**: `--server.address=0.0.0.0 --server.port=8501 --headless=true`, 포트 노출/프록시. `~/.tj_finance`·`raw_report`·`logs` 퍼시스턴트 볼륨.
9. **보안**: `OPENDART_API_KEY`는 이미지 미포함·런타임 secret 주입. Streamlit 무인증 → §9.
10. **제외/1회성**: QA Playwright(`scripts/qa/*`) 제외; `valuation_daily` matview 최초 populate(§7).

---

## 5. 배포 전략 4종 비교 (★리뷰로 D 승격)

| | **A. 풀-NAS** | **B. 하이브리드(NAS 서빙+Mac 컴퓨트)** | **C. NAS + 미니PC 컴퓨트노드** | **D. 미니PC 주 서버 + NAS 저장/백업** |
|---|---|---|---|---|
| DB(PG18) | NAS | NAS | NAS | **미니PC**(네이티브, btrfs·Docker 제약 없음) |
| 시각화 앱 | NAS | NAS | NAS | 미니PC 또는 NAS |
| 일상 수집/파싱 | NAS | NAS | NAS/미니PC | 미니PC |
| **풀백필** | NAS **8~15× 느림** | **Mac(빠름)** | 미니PC(파싱만 빠름, **DB쓰기는 NAS I/O**) | **미니PC(파싱+DB쓰기 둘 다 빠름)** |
| raw_report/백업 | NAS | NAS | NAS | **NAS(강점: RAID 대용량+Hyper Backup)** |
| Mac 은퇴 | ✅ | ❌(재처리 시 필요) | ✅ | ✅ |
| 추가지출(개략) | **HW티어 ₩70~110만** | ₩0(Mac 유지) | 미니PC ₩25~60만(+NAS 티어) | **미니PC ₩25~60만 + NAS는 저장용(정품NVMe 불필요)** |
| DB 병목 해결 | ❌(2코어 한계) | 재처리만(Mac) | 파싱만 | **✅ 완전**(강한 CPU+빠른 NVMe) |
| 목표 부합 | NAS중심 100%, 단 느림 | 절충(Mac 잔존) | NAS중심+파싱해결 | 목표 100%(단 “NAS중심” 아님) |
| 성격 | 재처리 드물면 최적 | 전환기 실용안 | 절충 | **기술적 최적/비용효율** |

> ★ **핵심 통찰(리뷰)**: 시스템-of-record DB를 **가장 약한 2코어 위**에 올리고 거기서 파싱·적재·앱까지 돌리는 A/C는 구조적으로 불리. **D는 권장-A와 비슷하거나 적은 돈(₩25~60만)으로 훨씬 강한 DB 호스트**(N305/Ryzen mini, 32~64GB, 값싼 고TBW NVMe, 네이티브 PG18)를 얻고 **파싱+DB쓰기 병목을 동시 해결**하며, NAS는 잘하는 일(대용량 RAID 저장+백업)에 집중. 단 사용자의 “NAS 중심” 정서와는 결이 다르므로 **정직하게 비교만** 제시.
> **갈림길**: 파서/매핑이 V2 이후 안정화되어 풀백필이 드물면 **A로 충분**. 재처리 빈발이면 **B(임시)·C·D**. 최고 비용효율·성능은 **D**.

---

## 6. 성능 분석 (근거 + ★리뷰 보강)

**일상 vs 풀백필 — 규모차 2~4 orders**
- **Daily**: 최근 3일 신규 corp만(보통 수~수십, 피크 수백), 단일워커 직렬 + corp당 timeout 600s → **수 분**. 메모리는 corp당 kill-and-respawn으로 150~300MB로 bound. **2코어/18GB 적합.**
- **풀백필**: 수만 XML + ~35만 PDF페이지. 병렬이나 NAS 유효 병렬 ≈2 + 코어당 ~2× + **동시성/서멀 스로틀** → **8~15×(★범위 상향)**. 샤딩·`--skip-done`·야간.
- **Gate B**는 원본 XML 재파싱(2×).

**정기 무거운 DB 작업(디스크 바운드 — 파일시스템/NVMe 관건)**
- ★ **PGDATA 파일시스템(btrfs 주의)**: Synology 기본 btrfs는 **CoW 단편화·쓰기증폭**(랜덤 8KB + WAL)으로 NVMe 이득을 잠식하고, **실행 중 PGDATA의 btrfs 스냅샷은 crash-consistent 아님**. → **PGDATA는 ext4 볼륨** 또는 **빈 datadir에 `chattr +C`(CoW off, 단 checksum·snapshot 트레이드오프)**. **DB 백업은 pg_dump/검증복원**이지 raw 스냅샷 아님. raw_report 볼륨은 btrfs+스냅샷 유용.
- ★ **matview refresh**: `CONCURRENTLY`는 11.2M행 결과를 **임시테이블로 만들어 diff**(추가 CPU/WAL + unique index 필요) → 평시 refresh의 ~2배. 개인용·야간이면 **plain `REFRESH`(짧은 락, 저비용)로 전환 권장** — E2에서 실측 비교.
- **VACUUM ANALYZE**(fact_v2 80GB): 단일스레드·I/O 바운드, NAS서 확연히 김.
- **가격 OHLCV sync**: 네트워크 바운드 ~20~40분(기기 무관), 샤딩.

**DB 튜닝 (`postgres_tuning.sql` 16GB 기준 → 재조정, ★autovacuum·restore·값 보정)**

| 파라미터 | 현(16GB) | NAS 18GB | NAS 32GB(권장) |
|---|---|---|---|
| shared_buffers | 4GB | 4~4.5GB | 8GB |
| effective_cache_size | 10GB | 11GB | **16~18GB(★하향)** |
| work_mem | 64MB | 32~48MB | 64MB |
| maintenance_work_mem | 1GB | 1GB | 2GB (restore 세션 2~4GB) |
| max_parallel_workers_per_gather | 4 | **1~2** | 1~2 |
| max_parallel_maintenance_workers | — | 1~2 | 1~2 |
| effective_io_concurrency | unset | **200**(Linux+SSD) | 200 |
| **autovacuum(★): fact_v2 등 고churn** | 기본 | scale_factor **0.01~0.02**, cost_limit **2000**, autovacuum_work_mem 256MB~1GB | 동일 |
| **FILLFACTOR(★): stock_prices/market_cap_daily** | 기본 | **~90**(HOT update, 인덱스 churn↓) | ~90 |

> 2코어에서 `work_mem×parallel×동시쿼리` 폭증 방지가 핵심(parallel 1~2). **restore 세션 한정**: maintenance_work_mem↑, autovacuum off, `pg_restore -j` 후 **필수 ANALYZE**(PG15 소스라 통계 미포함).

---

## 7. 이전 절차 (마이그레이션 런북 — ★리뷰로 순서·globals·ANALYZE·matview 보정)

**원칙: 검증 전 Mac DB 불가침. 롤백=앱 `DATABASE_URL`만.**

1. **NAS 준비**: DSM 7.2+, Container Manager, **PGDATA 볼륨(ext4/CoW off)** + HDD RAID1, PG18 컨테이너(로케일 생성), 앱 컨테이너.
2. **raw_report 로컬화**: SMB→로컬 볼륨. `rsync`(UTF-8) 후 **파일수·크기표본·md5표본 + NFC/NFD·대소문자 감사**.
3. **DB 논리 이전(순서 준수)**:
   a. `pg_dumpall --globals-only`(롤/권한) — **역할 먼저 생성**, `--no-owner`/`--role` 전략 결정.
   b. `pg_dump -Fc --compress=zstd`(PG18 클라이언트로 PG15 덤프, ~20~30GB 추정).
   c. 타깃 DB를 **소스와 동일 LC_COLLATE/LC_CTYPE로 생성** → `pg_restore -j2`.
   d. **`vacuumdb --analyze-in-stages`**(벤치·앱 전 필수 — 통계 없음).
   e. matview: **unique index 생성 → plain `REFRESH MATERIALIZED VIEW`(최초, CONCURRENTLY 불가)** → 이후 야간 정책(§6).
   f. 검증: **row count 대조 + `dq_assertions.py`(NAS DB) + 앱 쿼리 + ★콜레이션 정렬 표본(§10 E1b)**.
4. **설정 번역**(§4 1~10).
5. **1주 병행**(Mac authoritative + NAS shadow, 결과 비교).
6. **컷오버**: 앱·스케줄 NAS로. 전략 A=Mac 은퇴 / B=Mac 컴퓨트 / C·D=미니PC.

---

## 8. 예상 문제점 · 리스크 (★리뷰 보강)

| 리스크 | 영향 | 완화 |
|---|---|---|
| **R1600 2코어 풀백필 8~15×** | 재처리 수십 시간, 서멀 스로틀 | 샤딩·야간, 또는 전략 B/C/D |
| **★Synology NVMe 브랜드락** | 비정품 볼륨은 DSM 업데이트 시 오프라인 위험 | 정품 NVMe(SNV) 볼륨, 또는 D(미니PC) |
| **★로케일/콜레이션 불일치** | 한글 정렬·unique 조용히 오작동 | 소스와 동일 로케일/ICU, E1b 검증 |
| **★btrfs CoW/스냅샷** | NVMe 이득 잠식, 라이브 스냅샷 비일관 | PGDATA ext4/CoW off, 백업=pg_dump |
| **한글 폴더명 NFC/NFD** | 파일 매칭 실패(미묘) | rsync UTF-8 + 감사(E5) |
| **★DSM/컨테이너 자동업데이트 중단** | 실행 중 백필/VACUUM 중단 | 자동업데이트 창 고정, restart 정책, `--skip-done` |
| **★UPS 없이 정전**(btrfs DB) | 손상 위험 | **UPS 권장 승격** + DSM UPS 안전종료 + 컨테이너 stop_grace |
| **★3-2-1 위반**(백업이 DB호스트와 동일 기기) | 1기기 고장에 DB+백업 동시 상실 | **NAS 밖 1부** + restore_drill 지속 |
| **★NVMe 내구·서멀**(고churn WAL) | 스로틀·수명 | WAL bytes/day 실측(E2), DWPD 산정, 2베이 M.2 무냉각 유의 |
| macOS 알림 유실 | 실패 조용 | 이메일/DSM/webhook + 모니터링 |
| API키·Streamlit 무인증 | 유출·노출 | secret 주입, VPN(§9) |
| 2코어 동시성 경합 | 응답 저하 | 스케줄 간격, parallel 1~2 |

---

## 9. 원격 접속 비교 · 추천

| 방식 | 장점 | 단점 |
|---|---|---|
| **Tailscale VPN(추천)** | 포트 노출 0, 종단 암호화, 간단, 무인증 앱도 안전 | 기기마다 설치, ACL 설정 권장 |
| DDNS+리버스프록시(DSM)+HTTPS+인증 | 공개 URL 편의 | Streamlit 무인증 → 인증레이어 필수, 노출면↑ |

**추천: Tailscale** + ACL. 공개 노출은 위험.

---

## 10. 실험(PoC) 계획 — 결정 전 실측 (★리뷰로 4개 추가)

| # | 실험 | 목적 | 판정 |
|---|---|---|---|
| **E1** | NAS PG18 restore + `dq_assertions.py` + 앱 쿼리 | 15→18 호환·앱 동작, restore 시간 | PASS/시간 |
| **E1b★** | 소스 vs NAS 콜레이션/로케일·`ORDER BY 한글컬럼` top/bottom-N·unique 비교 | **silent-wrong 게이트** | 동일 |
| **E2** | matview **plain vs CONCURRENTLY** + fact_v2 VACUUM 실측(NVMe/ext4), **WAL bytes/day** | 정기 무거운 작업·NVMe 내구 | 분·GB/day |
| **E2b★** | btrfs(CoW on) vs `chattr +C` vs ext4 쓰기증폭 측정 | **PGDATA 파일시스템 결정** | 바이트/작업 |
| **E3** | `collect_new.py --days 3` NAS 완주 | 일상 적합성·벽시계·peak RAM | 분/GB |
| **E4** | 풀백필 샤드(50~100사) NAS vs Mac, **2워커+DB쓰기 포함** | 8~15× 실검증 | 배수 |
| **E4b★** | 백필 최대병렬 수시간 soak — CPU/NVMe 온도·스로틀 로깅 | 서멀 현실성(배수 유효성) | 스로틀 여부 |
| **E5** | raw_report Linux FS 복사 후 이름/체크섬 감사 | NFC/NFD·대소문자 | mismatch 0 |
| **E6** | Tailscale 외부 접속 | 사용성·지연 | OK |
| **E7** | 백필 2~3샤드+Gate B, peak RSS | 18GB 여유 | RSS<임계 |
| **E-power★** | UPS 안전종료/정전 중 쓰기 → 컨테이너 정상정지·WAL 복구·`--skip-done` 재개 | 무중단·크래시 복구 | 복구 OK |

> 저위험·필수(가능성): **E1·E1b·E3·E5·E-power**. 성능·티어: **E2·E2b·E4·E4b·E7**. 사용성: E6.

---

## 11. 의사결정 체크리스트 (사용자용)

1. **HW 티어**: 최소/권장/최대 — §3. (권장 실지출 ₩70~110만 = 약한 2코어 DB호스트임을 인지)
2. **배포 전략**: A 풀-NAS / B 하이브리드 / C 미니PC노드 / **D 미니PC 주서버+NAS 저장(비용효율·성능 최적)** — §5.
3. **원격 접속**: Tailscale(추천) — §9.
4. **이전 트리거**: ‘V2’/파서 안정화 시점. (안정화=A 가능, 재처리 빈발=B/C/D)
5. **PoC 순서**: E1·E1b·E3·E5·E-power(가능성) → E2·E2b·E4·E4b·E7(성능·티어) → E6.

---

## 검증 / 다음 단계 (이 문서)
- ✅ 인프라/DBA/Synology 전문가 리뷰 **반영 완료**(P1~P11: NVMe 브랜드락·콜레이션·btrfs·autovacuum·전략D·globals/ANALYZE·UPS/3-2-1·서멀·PoC 추가).
- 승인 시 `docs/nas_finance_server_plan.md` 저장 + 메모리 `nas-migration-plan` 갱신.
- **실행 안 함** — 사용자가 티어·전략·트리거 결정.
