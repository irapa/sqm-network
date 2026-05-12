SELECT
  local_time AS time,
  mag_arcsec2 AS "Sky Brightness",
  sensor_id
FROM sqm_readings
ORDER BY local_time;
