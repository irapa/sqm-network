SELECT
  local_time AS time,
  sun_alt_deg AS "Sun Altitude",
  moon_alt_deg AS "Moon Altitude"
FROM sqm_readings
ORDER BY local_time;
