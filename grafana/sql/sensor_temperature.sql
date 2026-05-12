SELECT
  local_time AS time,
  temperature_c AS "Sensor Temperature"
FROM sqm_readings
ORDER BY local_time;
