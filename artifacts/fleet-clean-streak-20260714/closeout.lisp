(:ringer-fleet-clean-streak
 :date "2026-07-14"
 :host "Aegis"
 :disposition :pass
 :target-streak 10
 :clean-runs 10
 :task-checks (:pass 40 :fail 0 :retries 0)
 :bead "hermes-ujgu"
 :paperclip "JAC-3415"
 :owned-fork (:url "https://github.com/JackReis/ringer-fleet.git"
              :head "47ccc11d416b057e1f46f2a93ca6c9f8efd2421c")
 :probes (:aegis-control-plane
          :talaris-cross-host
          :canonical-work-state
          :owned-ringer-fork)
 :accepted-runs
 ("fleet-clean-streak-01-20260714T190327Z-p99078"
  "fleet-clean-streak-02-20260714T190340Z-p99245"
  "fleet-clean-streak-03-20260714T190352Z-p99376"
  "fleet-clean-streak-04-20260714T190404Z-p99560"
  "fleet-clean-streak-05-20260714T190416Z-p99726"
  "fleet-clean-streak-06-20260714T190428Z-p99841"
  "fleet-clean-streak-07-20260714T190440Z-p99972"
  "fleet-clean-streak-08-20260714T190453Z-p265"
  "fleet-clean-streak-09-20260714T190505Z-p472"
  "fleet-clean-streak-10-20260714T190518Z-p588")
 :preserved-failures
 ((:kind :pre-dispatch-validation
   :cause "task model field incompatible with mock engine args template")
  (:kind :immutable-ringer-run
   :run-id "fleet-clean-streak-01-20260714T190230Z-p98710"
   :result (:pass 3 :fail 1)
   :cause "stale Talaris route assumption; corrected to :8082/api/health")
  (:kind :legacy-orphan
   :run-id "fleet-instruction-refresh-20260714-20260714T184851Z-p90068"
   :state :unfinished
   :pid :absent
   :counted nil))
 :evidence "/Users/hermes/Documents/Codex/2026-07-14/ringer-clean-streak/streak-evidence.json"
 :generated-at "2026-07-14T19:06:14Z")
