#!/bin/sh
# render_moss_breakup.sh [variant ...]  - Arnold renders of the scenes render_moss_breakup.py saved
# (cameras camTop1 / camView1 as cmds.camera names them: top and 3/4 views, 960 x 720, below-normal priority) into tests/_out/moss_breakup
export MAYA_DISABLE_CER=1
export MAYA_SKIP_USERSETUP_PY=1
OUT="$(cd "$(dirname "$0")" && pwd)/_out/moss_breakup"
cd "$OUT" || exit 1
VARS="${*:-before detail breakup carpet}"
for v in $VARS; do
  for cam in camView camTop; do
    start=$(date +%s)
    cmd //c start "" //belownormal //wait //b "C:/Program Files/Autodesk/Maya2024/bin/Render.exe" -r arnold \
        -cam "${cam}1" -x 960 -y 720 -rd "$OUT" -im "${v}_${cam}" -of png -ai:lve 1 "moss_$v.ma" > "render_${v}_${cam}.log" 2>&1
    echo "render ${v}_${cam} took $(( $(date +%s) - start )) s"
  done
done
