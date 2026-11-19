-- tj_asset request 4: remaining one-day close-price jumps over +-30.5% in the last 400 days.
WITH p AS (SELECT stock_code, trade_date, close_price::float8 c,
                  lag(close_price::float8) OVER (PARTITION BY stock_code ORDER BY trade_date) prev
           FROM stock_prices WHERE trade_date >= current_date - 400)
SELECT stock_code, trade_date, round((c / prev)::numeric, 3) AS ratio FROM p
WHERE prev > 0 AND abs(c / prev - 1) > 0.305 ORDER BY trade_date DESC;
