SELECT
  local_time AS time,
  usable_dark_sky AS "Usable Dark Sky"
FROM sqm_readings
ORDER BY local_time;
