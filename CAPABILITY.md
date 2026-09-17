---
description: Active-perception skill for inspecting Lite3's surroundings, finding or counting objects, and answering follow-up questions from the latest annotated eight-view 360-degree camera sweep.
---

# Inspect surroundings

Use `robonix/skill/find_object/scan` when the user asks Lite3 to look around,
search for, visually confirm, or count a named object such as a water bottle.
Pass the requested object name in `target`.

After a successful scan, use `robonix/skill/find_object/review_last_scan` for
follow-up questions about the same observation, such as “黄色的大门有没有打开”.
Pass the complete question in `question`. This call does not move the robot or
capture new images; it returns the latest contact sheet to Pilot for another
VLM reasoning round. Answer only from visible evidence. Say when the relevant
area is occluded, outside the camera view, or too ambiguous to determine.

The latest completed scan is retained in process memory for
`scan_memory_ttl_s` (15 minutes by default). If it is missing or expired, run a
new scan after applying the motion-safety checks below. Do not describe an old
scan as the current state, and do not silently rescan when the user asked about
the earlier observation.

Treat words such as "look around", "find", "search", "check whether there is",
"how many are there now", and their Chinese equivalents（环顾四周、寻找、找一下、
看看有没有、现在有几个）as requests for current visual evidence. Invoke this
skill even if Scene already contains an object with a matching label.

Scene's semantic object list is historical spatial memory: it can answer where
an object was previously observed, but it cannot prove that the object is still
present or provide a reliable current count. Do not use `scene/list_objects` as
a substitute for this live sweep. Use Scene directly only when the user asks
for a remembered or mapped location and does not request a new observation.

The skill captures first, then rotates the chassis 45 degrees counter-clockwise,
repeating this sequence eight times. The eighth rotation returns the robot to
its initial heading. It returns one JPEG contact sheet whose tiles are labelled
with `#1..#8`, a robot-relative direction, a signed centre angle, and a 45-degree
coverage interval. Positive angles are left/counter-clockwise; negative angles
are right/clockwise.

Pilot receives that image in its next VLM reasoning round. Report detections in
human robot-relative terms, for example “机器人右侧约 90°，大致位于右侧
67.5°–112.5° 范围内（#7）”. Never answer with only a tile number. Treat the
directions as relative to the robot's front at sweep start; because the final
rotation restores that heading, they are also relative to the robot's front
after a successful sweep.

The deployment may set `save_images: true` and `image_output_dir` to persist
each final annotated JPEG contact sheet. Saving is disabled by default. A
successful response includes the saved path in `detail`; container deployments
must mount the configured directory from the host if scans must persist.

Direction mapping:

- `#1`: front, centre `0°`, range `-22.5°..+22.5°`
- `#2`: front-left, centre `+45°`, range `+22.5°..+67.5°`
- `#3`: left, centre `+90°`, range `+67.5°..+112.5°`
- `#4`: rear-left, centre `+135°`, range `+112.5°..+157.5°`
- `#5`: rear, centre `180°`, range `157.5°..202.5°`
- `#6`: rear-right, centre `-135°`, range `-157.5°..-112.5°`
- `#7`: right, centre `-90°`, range `-112.5°..-67.5°`
- `#8`: front-right, centre `-45°`, range `-67.5°..-22.5°`

Rotation uses `robonix/primitive/chassis/move` with `rotate_deg`, not navigation.
On Lite3 this is an odometry-closed-loop command that always publishes a stop
when it succeeds, times out, or loses odometry. An interrupted sweep makes one
best-effort inverse rotation to restore the initial heading.

Before invoking the skill, ensure the standing robot has a clear rotation area,
no cables attached, stable footing, and an operator able to stop it. The front
camera cannot prove rear or leg-sweep clearance; this skill therefore does not
claim autonomous collision safety. Do not invoke it on stairs, slopes, loose
ground, near drop-offs, or among people or animals.

Dependencies are resolved through Atlas only:

- `robonix/primitive/camera/snapshot` over MCP
- `robonix/primitive/chassis/move` over gRPC
