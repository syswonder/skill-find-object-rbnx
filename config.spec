# Eight frames are fixed because Pilot receives a compact 4x2 contact sheet.
config:
  step_deg: 45.0
  # Pause after each completed rotation so gait vibration leaves the image.
  settle_s: 0.6
  # Keep the latest completed sweep in process memory for visual follow-up Q&A.
  # Expiry avoids answering a current-state question from stale surroundings.
  scan_memory_ttl_s: 900
  # Optionally persist the final annotated 4x2 JPEG contact sheet.
  save_images: false
  # Required when save_images is true. Mount this path from the host when the
  # skill runs in a container and the scans must survive container removal.
  image_output_dir: /data/robonix/find-object/scans
