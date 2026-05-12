SELECT
  local_time,
  sensor_id,
  site_name,
  mag_arcsec2,
  temperature_c,
  sun_alt_deg,
  moon_alt_deg,
  moon_phase_pct,
  usable_dark_sky
FROM sqm_readings
ORDER BY utc_time DESC
LIMIT 1;
