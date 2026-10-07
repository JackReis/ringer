#!/bin/bash
set -euo pipefail

# Antigravity (agy) subscription lane. Keeps this worker on the consumer
# Antigravity OAuth login under ~/.gemini/antigravity-cli/. Caller-selected
# API keys, OpenRouter routes, and alternate config roots are not trusted.
# Restricted anthropic/google/openai model selectors are allowed on this
# wrapper only because Ringer registers engines/agy-oauth.sh as an alternate
# trusted family wrapper (alongside claude-oauth / gemini-oauth / codex-oauth).
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL ANTHROPIC_API_BASE
unset CLAUDE_API_KEY CLAUDE_BASE_URL CLAUDE_API_BASE CLAUDE_CONFIG_DIR
unset OPENAI_API_KEY OPENAI_BASE_URL OPENAI_API_BASE OPENAI_API_HOST
unset OPENROUTER_API_KEY OPENROUTER_BASE_URL
unset GEMINI_API_KEY GOOGLE_API_KEY GOOGLE_APPLICATION_CREDENTIALS
unset GOOGLE_GENAI_USE_VERTEXAI GOOGLE_CLOUD_PROJECT GOOGLE_CLOUD_LOCATION
unset GOOGLE_GEMINI_BASE_URL GEMINI_CLI_HOME GEMINI_SYSTEM_MD
unset GEMINI_CLI_SYSTEM_SETTINGS_PATH
unset AGY_API_KEY AGY_BASE_URL AGY_HOME AGY_CONFIG_DIR
unset ANTIGRAVITY_API_KEY ANTIGRAVITY_BASE_URL ANTIGRAVITY_HOME
unset RINGER_OAUTH_TEST_MODE RINGER_TEST_AGY_BIN

agy_bin=agy

fail() {
  printf '%s\n' "agy-oauth.sh: blocked ambiguous or non-OAuth invocation; use the standard Antigravity (agy) consumer OAuth login" >&2
  exit 64
}

# Require a real stored Antigravity OAuth credential; never print it.
creds="${HOME:?}/.gemini/antigravity-cli/antigravity-oauth-token"
[[ -f "$creds" ]] || fail
python3 - "$creds" <<'PY' >/dev/null 2>&1 || fail
import json
import sys

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result

try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        stored = json.load(stream, object_pairs_hook=unique_object)
    token = stored.get("token") if isinstance(stored, dict) else None
    valid = (
        isinstance(stored, dict)
        and stored.get("auth_method") == "consumer"
        and isinstance(token, dict)
        and type(token.get("access_token")) is str
        and len(token["access_token"]) > 20
        and type(token.get("refresh_token")) is str
        and len(token["refresh_token"]) > 20
    )
except (OSError, ValueError, json.JSONDecodeError):
    valid = False
raise SystemExit(0 if valid else 1)
PY
unset creds

# Allow only Antigravity-served slugs observed on this host (agy models).
# Keep this list exact — do not accept OpenRouter or first-party API selectors.
normalize_model() {
  local original="$1" model="$1" lower
  [[ -n "$model" && "$model" != -* ]] || fail
  lower="$(printf '%s' "$model" | LC_ALL=C tr '[:upper:]' '[:lower:]')"
  case "$lower" in
    openrouter/*|anthropic/*|openai/*|google/*|moonshotai/*|api/*) fail ;;
  esac
  case "$lower" in
    gemini-3.8-flash-high|gemini-3.8-flash-medium|gemini-3.8-flash-low|\
gemini-3.7-flash-high|gemini-3.7-flash-medium|gemini-3.7-flash-low|\
gemini-3.6-flash-high|gemini-3.6-flash-medium|gemini-3.6-flash-low|\
gemini-3.1-pro-high|gemini-3.1-pro-low|\
claude-sonnet-4-6|claude-opus-4-6-thinking|\
gpt-oss-120b-medium)
      printf '%s' "$lower" ;;
    *) fail ;;
  esac
}

args=("$@")
model_seen=0
prompt_seen=0
output_seen=0
effort_seen=0
mode_seen=0
timeout_seen=0

for ((i = 0; i < ${#args[@]}; i++)); do
  item="${args[$i]}"
  case "$item" in
    --)
      fail ;;
    -m|--model)
      (( model_seen == 0 && i + 1 < ${#args[@]} )) || fail
      [[ -n "${args[$((i + 1))]}" && "${args[$((i + 1))]}" != -* ]] || fail
      args[$((i + 1))]="$(normalize_model "${args[$((i + 1))]}")"
      model_seen=1
      ((i += 1))
      ;;
    --model=*)
      (( model_seen == 0 )) || fail
      value="${item#--model=}"
      [[ -n "$value" ]] || fail
      args[$i]="--model=$(normalize_model "$value")"
      model_seen=1
      ;;
    -p|--prompt|--print)
      (( prompt_seen == 0 && i + 1 < ${#args[@]} )) || fail
      [[ -n "${args[$((i + 1))]}" ]] || fail
      # Canonicalize to --prompt so Ringer's args_template and -p are equivalent.
      args[$i]="--prompt"
      prompt_seen=1
      ((i += 1))
      ;;
    --prompt=*|--print=*)
      (( prompt_seen == 0 )) || fail
      value="${item#*=}"
      [[ -n "$value" ]] || fail
      args[$i]="--prompt=$value"
      prompt_seen=1
      ;;
    --output-format)
      (( output_seen == 0 && i + 1 < ${#args[@]} )) || fail
      value="${args[$((i + 1))]}"
      [[ "$value" == text || "$value" == json || "$value" == stream-json ]] || fail
      output_seen=1
      ((i += 1))
      ;;
    --output-format=*)
      (( output_seen == 0 )) || fail
      value="${item#--output-format=}"
      [[ "$value" == text || "$value" == json || "$value" == stream-json ]] || fail
      output_seen=1
      ;;
    --effort)
      (( effort_seen == 0 && i + 1 < ${#args[@]} )) || fail
      value="${args[$((i + 1))]}"
      [[ "$value" == low || "$value" == medium || "$value" == high || "$value" == max ]] || fail
      effort_seen=1
      ((i += 1))
      ;;
    --effort=*)
      (( effort_seen == 0 )) || fail
      value="${item#--effort=}"
      [[ "$value" == low || "$value" == medium || "$value" == high || "$value" == max ]] || fail
      effort_seen=1
      ;;
    --mode)
      (( mode_seen == 0 && i + 1 < ${#args[@]} )) || fail
      value="${args[$((i + 1))]}"
      [[ "$value" == accept-edits || "$value" == plan ]] || fail
      mode_seen=1
      ((i += 1))
      ;;
    --mode=*)
      (( mode_seen == 0 )) || fail
      value="${item#--mode=}"
      [[ "$value" == accept-edits || "$value" == plan ]] || fail
      mode_seen=1
      ;;
    --print-timeout)
      (( timeout_seen == 0 && i + 1 < ${#args[@]} )) || fail
      value="${args[$((i + 1))]}"
      [[ "$value" =~ ^[0-9]+[smhd]?$ ]] || fail
      timeout_seen=1
      ((i += 1))
      ;;
    --print-timeout=*)
      (( timeout_seen == 0 )) || fail
      value="${item#--print-timeout=}"
      [[ "$value" =~ ^[0-9]+[smhd]?$ ]] || fail
      timeout_seen=1
      ;;
    --dangerously-skip-permissions|--sandbox|--disable-slash-commands)
      ;;
    *)
      fail ;;
  esac
done

(( model_seen == 1 && prompt_seen == 1 )) || fail
exec "$agy_bin" "${args[@]}"
