# 신규 공시 자동 수집 (launchd, 매일 18:00 + 잠자기 깨우기)

`scripts/collect_new.py`(탐지→동기화→다운로드→파싱·표준화)를 매일 18:00 자동 실행한다.
맥북이 잠자기여도 `pmset` 예약 wake(17:58)로 깨운 뒤 launchd 가 18:00 에 실행한다.

## 설치 (최초 1회)

```bash
# 1) plist 배치 (이미 복사돼 있으면 생략)
cp deploy/launchd/com.tjfinance.collect.plist ~/Library/LaunchAgents/
mkdir -p logs

# 2) launchd 등록 (사용자 세션)
launchctl load -w ~/Library/LaunchAgents/com.tjfinance.collect.plist

# 3) 잠자기에서 17:58 깨우기 (sudo 필요, 매일)
sudo pmset repeat wakeorpoweron MTWRFSU 17:58:00
```

## 확인 / 운영

```bash
launchctl list | grep tjfinance              # 등록 확인
pmset -g sched                               # 예약 wake 확인
launchctl start com.tjfinance.collect        # 지금 즉시 1회 실행(테스트)
tail -f logs/collect.out.log                 # 진행 로그
```

## 해제

```bash
launchctl unload -w ~/Library/LaunchAgents/com.tjfinance.collect.plist
sudo pmset repeat cancel                      # 예약 wake 해제
```

## 참고
- 잠자기(sleep)에서는 wake 후 실행됨. **완전 종료(shutdown)** 상태는 기종(Apple Silicon)에 따라
  power-on 이 안 될 수 있음 — 그 경우 다음 부팅/wake 시 누락분이 실행됨(StartCalendarInterval).
- `--days 3`: 하루 걸러도 겹치는 창이라 누락 방지(멱등).
- DART 키는 `.env`(OPENDART_API_KEY)에서 자동 로드(절대경로).
