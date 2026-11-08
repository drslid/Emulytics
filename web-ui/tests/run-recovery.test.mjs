import assert from 'node:assert/strict';
import {test} from 'node:test';
import {diagnosisMessage, parseRetryDraft, retryKey} from '../lib/run-recovery.ts';

test('a pending retry remains scoped to its user and source and keeps one immutable intent', () => {
 const draft={request_id:'5cccded5-bc64-4315-afb4-1a2cc9880efb',device_ids:['phone-one','phone-two']};
 assert.deepEqual(parseRetryDraft(JSON.parse(JSON.stringify(draft))),draft);
 assert.notEqual(retryKey('a','source'),retryKey('b','source'));
 assert.notEqual(retryKey('a','source'),retryKey('a','other'));
 for(const value of [null,[],{...draft,request_id:'-'.repeat(36)},{...draft,device_ids:[]},{...draft,device_ids:['duplicate','duplicate']},{...draft,device_ids:['invalid device']},{...draft,secret:'unexpected'}]) assert.equal(parseRetryDraft(value),null);
});

test('diagnosis labels do not confuse uncertain effects with a retryable failure', () => {
 assert.match(diagnosisMessage('uncertain_effect'),/incertain/);
 assert.match(diagnosisMessage('application_missing'),/application/);
 assert.match(diagnosisMessage('constructor'),/Consultez/);
});
