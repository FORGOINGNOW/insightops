-- Canonical session-level conversion: one row per session, paid order source of truth.
SELECT period,channel,COUNT(*) AS sessions,SUM(converted) AS conversions,
       1.0*SUM(converted)/COUNT(*) AS conversion_rate
FROM session_facts GROUP BY period,channel ORDER BY period,channel;

-- Daily revenue must not be multiplied by order line cardinality.
WITH item_totals AS (
  SELECT order_id,SUM(amount_cents) AS item_cents FROM order_items GROUP BY order_id
)
SELECT COUNT(*) AS orders,SUM(o.amount_cents) AS order_cents,SUM(i.item_cents) AS item_cents
FROM orders o JOIN item_totals i USING(order_id);

-- Running revenue by event date; partitions explicitly identify analysis grain.
WITH daily AS (
 SELECT substr(occurred_at,1,10) AS day,SUM(revenue_cents) AS revenue_cents
 FROM session_facts GROUP BY substr(occurred_at,1,10)
)
SELECT day,revenue_cents,SUM(revenue_cents) OVER (ORDER BY day) AS cumulative_cents FROM daily;

-- Before/after channel mix: adjacent-period comparison using a window function.
WITH strata AS (
 SELECT period,channel,COUNT(*) AS n,AVG(converted) AS rate
 FROM session_facts GROUP BY period,channel
)
SELECT *,rate-LAG(rate) OVER (PARTITION BY channel ORDER BY CASE period WHEN 'before' THEN 0 ELSE 1 END) AS rate_change
FROM strata;
