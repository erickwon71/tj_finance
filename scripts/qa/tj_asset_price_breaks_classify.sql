-- tj_asset request 4: classify one-day close-price jumps over +-30.5% (last 400 days).
--  halt_unscaled : the jump touches a zero-volume day whose close_price = close_raw while the
--                  neighbouring traded day carries a different factor (halt rows not rescaled)
--  stale_basis   : adjusted price jumps but raw close is continuous (R338 boundary, not refetched yet)
--  raw_move      : the raw close jumps too (real price move or source-side boundary)
WITH p AS (
  SELECT stock_code, trade_date, close_price::float8 c, close_raw::float8 r, volume,
         lag(close_price::float8) OVER w pc, lag(close_raw::float8) OVER w pr, lag(volume) OVER w pv
  FROM stock_prices WHERE trade_date >= current_date - 401
  WINDOW w AS (PARTITION BY stock_code ORDER BY trade_date)
), j AS (
  SELECT * FROM p WHERE trade_date >= current_date - 400 AND pc > 0 AND abs(c / pc - 1) > 0.305
)
SELECT CASE
         WHEN (volume = 0 AND c = r) OR (pv = 0 AND pc = pr) THEN 'halt_unscaled'
         WHEN r > 0 AND pr > 0 AND abs(ln(c / pc)) > abs(ln(r / pr)) + 0.05 THEN 'stale_basis'
         ELSE 'raw_move' END AS kind,
       count(*) AS n, count(DISTINCT stock_code) AS stocks,
       string_agg(DISTINCT stock_code, ',') AS codes
FROM j GROUP BY 1 ORDER BY 1;
