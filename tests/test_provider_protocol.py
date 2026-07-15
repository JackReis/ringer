from __future__ import annotations
import copy, json, subprocess, sys, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
import context_packet as cp
import provider_protocol as pp

NOW=datetime(2026,7,14,12,5,tzinfo=timezone.utc)
LATER=datetime(2026,7,14,12,16,tzinfo=timezone.utc)
ROOT=Path(__file__).resolve().parents[1]

def packet():
 return cp.loads_packet((ROOT/'fixtures/context-packet-v1/sealed.json').read_bytes(),now=NOW)
def envelope(): return pp.make_envelope(envelope_id='env-1',provider_id='provider-1',model_id='model-1',request_id='request-1',packet=packet(),now=NOW)

def fresh_packet():
 p={"schema_version":cp.SCHEMA_VERSION,"packet_id":"fresh-1","subject":"fresh","created_at":"2026-07-14T12:16:00Z","expires_at":"2026-07-14T12:30:00Z","evidence":[{"evidence_id":"e-1","media_type":"text/plain","content":"fresh","provenance":{"source":"adapter:test","observed_at":"2026-07-14T12:16:00Z","retrieved_at":"2026-07-14T12:16:00Z"},"freshness":{"max_age_seconds":900}}]}
 return cp.seal_packet(p)

class ProviderProtocolTests(unittest.TestCase):
 def test_constructor_preserves_and_isolates_packet(self):
  p=packet(); before=cp.canonical_json_bytes(p); e=pp.make_envelope(envelope_id='e',provider_id='p',model_id='m',request_id='r',packet=p,now=NOW)
  self.assertEqual(cp.canonical_json_bytes(p),before); self.assertEqual(cp.canonical_json_bytes(e['packet']),before); e['packet']['subject']='x'; self.assertEqual(cp.canonical_json_bytes(p),before)
 def test_metadata_is_external_and_nested_packet_unchanged(self):
  p=packet(); e=envelope(); self.assertEqual(set(e),{'protocol_version','envelope_id','provider_id','model_id','request_id','packet'}); self.assertEqual(e['packet'],p); self.assertNotIn('provider_protocol',e['packet'])
 def test_round_trip_preserves_packet_digest_and_bytes(self):
  e=envelope(); got=pp.loads_envelope(pp.dumps_envelope(e),now=NOW); self.assertEqual(cp.canonical_json_bytes(got['packet']),cp.canonical_json_bytes(e['packet'])); self.assertEqual(got['packet']['integrity']['packet_sha256'],e['packet']['integrity']['packet_sha256'])
 def test_existing_packet_fixture_and_plain_api_remain_compatible(self):
  p=packet(); self.assertEqual(cp.dumps_packet(p),(ROOT/'fixtures/context-packet-v1/sealed.json').read_text()); self.assertEqual(pp.make_envelope(envelope_id='e',provider_id='p',model_id='m',request_id='r',packet=p,now=NOW)['packet'],p)
 def test_unknown_packet_and_envelope_fields_fail(self):
  e=envelope(); e['packet']['provider_protocol']={};
  with self.assertRaises(cp.ContextPacketValidationError): pp.validate_envelope(e,now=NOW)
  e=envelope(); e['extra']=1
  with self.assertRaises(pp.ProviderProtocolValidationError): pp.validate_envelope(e,now=NOW)
 def test_each_missing_required_field_fails(self):
  for key in tuple(envelope()):
   with self.subTest(key=key):
    e=envelope(); del e[key]
    with self.assertRaises(pp.ProviderProtocolValidationError): pp.validate_envelope(e,now=NOW)
 def test_wrong_version_and_invalid_identifiers_fail(self):
  e=envelope(); e['protocol_version']='v2'
  with self.assertRaises(pp.ProviderProtocolValidationError): pp.validate_envelope(e,now=NOW)
  for value in ('','x'*129,'-bad','bad id',3):
   with self.subTest(value=value):
    e=envelope(); e['provider_id']=value
    with self.assertRaises(pp.ProviderProtocolValidationError): pp.validate_envelope(e,now=NOW)
 def test_duplicate_keys_at_envelope_and_packet_depth_fail(self):
  raw=pp.dumps_envelope(envelope())
  for bad in (raw.replace('{','{"protocol_version":"provider-protocol.v1",',1),raw.replace('"packet_id":','"packet_id":"dup","packet_id":',1)):
   with self.assertRaises(pp.ProviderProtocolParseError): pp.loads_envelope(bad,now=NOW)
 def test_malformed_wire_types_and_surrogates_normalize(self):
  for raw in ('[]','{',b'\xff','{"n":1.2}','{"n":NaN}','{"provider_id":"\\ud800"}'):
   with self.subTest(raw=raw):
    with self.assertRaises(pp.ProviderProtocolError): pp.loads_envelope(raw,now=NOW)
 def test_wire_limit_checked_before_parser(self):
  raw=pp.dumps_envelope(envelope()); exact=raw+' '*(pp.MAX_WIRE_BYTES-len(raw.encode()))
  self.assertEqual(pp.loads_envelope(exact,now=NOW),envelope())
  with mock.patch.object(pp.json,'loads') as parser:
   with self.assertRaisesRegex(pp.ProviderProtocolParseError,'wire size'): pp.loads_envelope(exact+' ',now=NOW)
   parser.assert_not_called()
 def test_packet_content_and_provenance_tamper_fail(self):
  for mutate in (lambda e:e['packet']['evidence'][0].__setitem__('content','bad'),lambda e:e['packet']['evidence'][0]['provenance'].__setitem__('source','bad')):
   e=envelope(); mutate(e)
   with self.assertRaises(cp.ContextPacketValidationError): pp.validate_envelope(e,now=NOW)
 def test_freshness_modes(self):
  with self.assertRaises(cp.ContextPacketValidationError): pp.validate_envelope(envelope(),now=LATER)
  pp.validate_envelope(envelope(),now=LATER,require_fresh=False); self.assertTrue(pp.dumps_envelope(envelope()))
 def test_refresh_expired_once_and_preserves_metadata(self):
  class A:
   calls=0
   def fetch_packet(self,**kw): self.calls+=1; return fresh_packet()
  a=A(); old=envelope(); got=pp.refresh_envelope(old,a,now=LATER); self.assertEqual(a.calls,1); self.assertEqual({k:got[k] for k in old if k!='packet'},{k:old[k] for k in old if k!='packet'}); self.assertNotEqual(got['packet'],old['packet'])
 def test_refresh_passes_exact_ids_clock_and_isolated_copy(self):
  old=envelope(); original=copy.deepcopy(old); seen={}
  class A:
   def fetch_packet(self,**kw): seen.update(kw); kw['previous_packet']['subject']='mutated'; return fresh_packet()
  pp.refresh_envelope(old,A(),now=LATER); self.assertEqual(old,original); self.assertEqual(seen['provider_id'],'provider-1'); self.assertEqual(seen['model_id'],'model-1'); self.assertEqual(seen['request_id'],'request-1'); self.assertIs(seen['now'],LATER)
 def test_adapter_exception_chains_without_retry(self):
  class A:
   calls=0
   def fetch_packet(self,**kw): self.calls+=1; raise RuntimeError('boom')
  a=A()
  with self.assertRaises(pp.ProviderProtocolAdapterError) as caught: pp.refresh_envelope(envelope(),a,now=LATER)
  self.assertIsInstance(caught.exception.__cause__,RuntimeError); self.assertEqual(a.calls,1)
 def test_invalid_adapter_results_fail_closed(self):
  bad=[None,{},packet()]
  bad[2]['extra']=1
  for result in bad:
   class A:
    def fetch_packet(self,**kw): return result
   with self.subTest(result=result):
    with self.assertRaises(pp.ProviderProtocolError): pp.refresh_envelope(envelope(),A(),now=LATER)
 def test_naive_refresh_clock_fails_before_call(self):
  class A:
   calls=0
   def fetch_packet(self,**kw): self.calls+=1
  a=A()
  with self.assertRaises(pp.ProviderProtocolValidationError): pp.refresh_envelope(envelope(),a,now=datetime(2026,7,14))
  self.assertEqual(a.calls,0)
 def test_schema_is_closed_and_matches_runtime(self):
  s=json.loads((ROOT/'schema/provider-protocol.v1.json').read_text()); self.assertFalse(s['additionalProperties']); self.assertEqual(set(s['required']),set(s['properties'])); self.assertEqual(s['properties']['protocol_version']['const'],pp.PROTOCOL_VERSION); self.assertEqual(s['$defs']['id']['maxLength'],128); self.assertEqual(set(s['properties'])-{'packet'},{'protocol_version','envelope_id','provider_id','model_id','request_id'})
 def test_golden_fixture_is_byte_exact_and_deterministic(self):
  raw=(ROOT/'fixtures/provider-protocol-v1/envelope.json').read_text(); got=pp.loads_envelope(raw,now=NOW); self.assertEqual(pp.dumps_envelope(got),raw); self.assertEqual(pp.dumps_envelope(got),pp.dumps_envelope(got))
 def test_manifest_structure_placeholders_and_issue_fields(self):
  m=json.loads((ROOT/'templates/provider-context/manifest.json').read_text()); self.assertEqual(m['max_parallel'],1); self.assertEqual(len(m['tasks']),1); t=m['tasks'][0]; self.assertEqual(t['key'],'provider-context-{{PROVIDER_ID}}-{{MODEL_ID}}'); self.assertEqual(t['task_type'],'data-pipeline'); self.assertEqual(t['expect_files'],['{{OUTPUT_ENVELOPE}}']); self.assertEqual(m['paperclip_issue'],'{{PAPERCLIP_ISSUE}}'); self.assertEqual(m['bead_id'],'{{BEAD_ID}}')
 def test_manifest_has_all_exact_provider_placeholders_no_secret_values(self):
  text=(ROOT/'templates/provider-context/manifest.json').read_text();
  for p in ('{{PROVIDER_ID}}','{{MODEL_ID}}','{{REQUEST_ID}}','{{ENVELOPE_ID}}','{{PACKET_PATH}}','{{OUTPUT_ENVELOPE}}'): self.assertIn(p,text)
  for forbidden in ('api_key','api-key','token_value','credential_value'): self.assertNotIn(forbidden,text.lower())
 def test_cli_matching_ids_succeeds_and_mismatch_fails(self):
  path=ROOT/'fixtures/provider-protocol-v1/envelope.json'; base=[sys.executable,str(ROOT/'provider_protocol.py'),'validate',str(path),'--envelope-id','env-golden','--provider-id','provider-1','--model-id','model-1','--request-id','request-1','--now','2026-07-14T12:05:00Z']; ok=subprocess.run(base,text=True,capture_output=True); self.assertEqual(ok.returncode,0,ok.stderr)
  for flag in ('--envelope-id','--provider-id','--model-id','--request-id'):
   bad=base.copy(); bad[bad.index(flag)+1]='wrong'; run=subprocess.run(bad,text=True,capture_output=True); self.assertNotEqual(run.returncode,0); self.assertIn('mismatch',run.stderr)
 def test_adapter_protocol_runtime_shape(self):
  class A:
   def fetch_packet(self,**kw): return fresh_packet()
  self.assertIsInstance(A(),pp.ProviderAdapter)
 def test_constructor_rejects_naive_clock_and_does_not_mutate(self):
  p=packet(); before=copy.deepcopy(p)
  with self.assertRaises(cp.ContextPacketValidationError): pp.make_envelope(envelope_id='e',provider_id='p',model_id='m',request_id='r',packet=p,now=datetime(2026,1,1))
  self.assertEqual(p,before)
 def test_refresh_result_isolated_from_adapter_owned_packet(self):
  returned=fresh_packet()
  class A:
   def fetch_packet(self,**kw): return returned
  got=pp.refresh_envelope(envelope(),A(),now=LATER); got['packet']['subject']='consumer mutation'; self.assertNotEqual(got['packet'],returned)
 def test_refresh_rejects_future_packet(self):
  p=fresh_packet(); p['created_at']='2026-07-14T12:17:00Z'; p['evidence'][0]['provenance']['retrieved_at']='2026-07-14T12:17:00Z'; p['evidence'][0]['provenance']['observed_at']='2026-07-14T12:17:00Z'; p=cp.seal_packet({k:v for k,v in p.items() if k!='integrity'} | {'evidence':[{k:v for k,v in p['evidence'][0].items() if k!='integrity'}]})
  class A:
   def fetch_packet(self,**kw): return p
  with self.assertRaises(pp.ProviderProtocolAdapterError): pp.refresh_envelope(envelope(),A(),now=LATER)
 def test_refresh_rejects_expired_packet(self):
  class A:
   def fetch_packet(self,**kw): return packet()
  with self.assertRaises(pp.ProviderProtocolAdapterError): pp.refresh_envelope(envelope(),A(),now=LATER)
 def test_refresh_rejects_non_object_packet(self):
  class A:
   def fetch_packet(self,**kw): return []
  with self.assertRaises(pp.ProviderProtocolAdapterError): pp.refresh_envelope(envelope(),A(),now=LATER)
 def test_loads_rejects_non_string_input(self):
  with self.assertRaises(pp.ProviderProtocolParseError): pp.loads_envelope(42,now=NOW)
 def test_all_metadata_identifiers_are_independently_validated(self):
  for key in ('envelope_id','provider_id','model_id','request_id'):
   e=envelope(); e[key]='bad value'
   with self.subTest(key=key):
    with self.assertRaises(pp.ProviderProtocolValidationError): pp.validate_envelope(e,now=NOW)
 def test_manifest_check_binds_each_identifier_to_matching_flag(self):
  check=json.loads((ROOT/'templates/provider-context/manifest.json').read_text())['tasks'][0]['check']
  for flag,name in (('--envelope-id','ENVELOPE_ID'),('--provider-id','PROVIDER_ID'),('--model-id','MODEL_ID'),('--request-id','REQUEST_ID')): self.assertIn(f'{flag} {{{{{name}}}}}',check)
 def test_cli_invalid_packet_is_diagnostic(self):
  raw=json.loads((ROOT/'fixtures/provider-protocol-v1/envelope.json').read_text()); raw['packet']['subject']='tampered'; path=ROOT/'fixtures/provider-protocol-v1/.invalid-test.json'; path.write_text(json.dumps(raw))
  try:
   run=subprocess.run([sys.executable,str(ROOT/'provider_protocol.py'),'validate',str(path),'--envelope-id','env-golden','--provider-id','provider-1','--model-id','model-1','--request-id','request-1','--now','2026-07-14T12:05:00Z'],text=True,capture_output=True); self.assertNotEqual(run.returncode,0); self.assertIn('validation failed',run.stderr)
  finally: path.unlink(missing_ok=True)

if __name__=='__main__': unittest.main(verbosity=2)
