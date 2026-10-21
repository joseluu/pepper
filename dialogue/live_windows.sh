#!/bin/sh
# Lance live.py avec le Python et le son de Windows (la sortie son de WSLg hache).
# Les identifiants Google de WSL sont transmis à Windows (WSLENV, chemin traduit).
cd "$(dirname "$0")" || exit 1
UV=$(command -v uv.exe || ls /mnt/c/Users/*/.local/bin/uv.exe 2>/dev/null | head -1)
[ -n "$UV" ] || { echo "uv.exe introuvable côté Windows"; exit 1; }
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/gcloud/application_default_credentials.json"
export PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
export WSLENV="${WSLENV:+$WSLENV:}GOOGLE_APPLICATION_CREDENTIALS/p:PYTHONIOENCODING:PYTHONUNBUFFERED"
exec "$UV" run --script "$(wslpath -w live.py)" "$@"
