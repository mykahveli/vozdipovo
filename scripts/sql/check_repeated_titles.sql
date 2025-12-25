SELECT
  lower(trim(titulo)) AS norm_title,
  COUNT(*) AS n
FROM news_articles
WHERE review_status = 'SUCCESS'
GROUP BY lower(trim(titulo))
HAVING COUNT(*) > 1
ORDER BY n DESC, norm_title ASC
LIMIT 50;
