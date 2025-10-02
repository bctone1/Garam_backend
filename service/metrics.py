# service/metrics.py
from sqlalchemy import text
from sqlalchemy.orm import Session
from crud import model as crud_model


## 주석 참고
def recompute_model_metrics(db: Session) -> None:
    """
    이번 달 기준 운영 지표를 집계해 model 싱글톤에 저장한다.
    - avg_response_time_ms : 어시스턴트 응답 지연(ms) 평균
    - month_conversations  : 생성된 세션 수
    - accuracy             : 피드백 기반 정확도(%). 숫자 평점(>=4) 또는 helpful/unhelpful 해석
    - uptime_percent       : 어시스턴트 응답 성공률(%). extra_data->>'error' 없음 = 성공
    """
    # 어시스턴트 메시지의 응답지연 평균(이번 달). 값이 없으면 0
    avg_ms = db.execute(text("""
        SELECT COALESCE(AVG(response_latency_ms), 0)
        FROM message
        WHERE role='assistant' AND created_at >= date_trunc('month', now())
    """)).scalar() or 0

    # 이번 달 생성된 대화 세션 개수
    month_convs = db.execute(text("""
        SELECT COUNT(*) FROM chat_session
        WHERE created_at >= date_trunc('month', now())
    """)).scalar() or 0

    # 정확도(%): rating이 숫자면 4점 이상을 정답(1)으로, 문자열이면 helpful=1, unhelpful=0로 환산
    # 숫자 캐스팅 안전을 위해 정규식으로 숫자 문자열만 ::numeric 처리
    accuracy = db.execute(text("""
        SELECT COALESCE(
          AVG(
            CASE
              WHEN rating ~ '^[0-9]+(\\.[0-9]+)?$' AND rating::numeric >= 4 THEN 1
              WHEN rating ILIKE 'helpful'   THEN 1
              WHEN rating ILIKE 'unhelpful' THEN 0
              ELSE NULL   -- 해석 불가 데이터는 평균에서 제외
            END
          ) * 100, 0
        )
        FROM feedback
        WHERE created_at >= date_trunc('month', now())
    """)).scalar() or 0

    # 가동률(%): 이번 달 어시스턴트 메시지 중 오류가 없는 비율
    # 분모가 0이면 NULL → COALESCE로 100 처리(무가동 기간 오해 방지)
    uptime = db.execute(text("""
        SELECT COALESCE(
          (COUNT(*) FILTER (WHERE (extra_data->>'error') IS NULL))::float
          / NULLIF(COUNT(*),0) * 100, 100
        )
        FROM message
        WHERE role='assistant' AND created_at >= date_trunc('month', now())
    """)).scalar() or 100

    # 집계값을 싱글톤 model에 반영
    crud_model.update_metrics(
        db,
        accuracy=float(accuracy),                  # Numeric(5,2) 대상
        avg_response_time_ms=int(avg_ms),         # Integer 대상
        month_conversations=int(month_convs),     # Integer 대상
        uptime_percent=float(uptime),             # Numeric(5,2) 대상
    )
