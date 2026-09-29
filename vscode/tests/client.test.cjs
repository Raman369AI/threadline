const {test} = require('node:test');
const assert = require('node:assert/strict');
const {mkdtemp, writeFile, rm} = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {AnalyzerClient} = require('../dist/client');

test('subprocess failures, framing, timeout, and disposal reject requests', async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'threadline-client-'));
  const python = process.env.THREADLINE_TEST_PYTHON || 'python3';
  const clients = [];
  const make = async source => {
    const runner = path.join(temp, 'runner-' + clients.length + '.py');
    await writeFile(runner, source);
    const client = new AnalyzerClient(python, runner, temp, () => {}); clients.push(client); return client;
  };
  try {
    const malformed = await make('import sys\nsys.stdin.readline()\nprint("not json", flush=True)\n');
    await assert.rejects(malformed.request({op:'test'}), /Invalid analyzer output/);
    const silent = await make('import time\ntime.sleep(60)\n');
    await assert.rejects(silent.request({op:'test'}, 100), /timed out/);
    assert.equal(silent.stopped, true);
    const closing = await make('import time\ntime.sleep(60)\n');
    const pending = closing.request({op:'test'}); closing.dispose();
    await assert.rejects(pending, /closed/);
    const absent = new AnalyzerClient(path.join(temp, 'missing-python'), 'none', temp, () => {}); clients.push(absent);
    await assert.rejects(absent.request({op:'test'}), /Cannot start Python/);
    const huge = await make('import sys\nsys.stdin.readline()\nsys.stdout.write("x" * (17 * 1024 * 1024))\nsys.stdout.flush()\n');
    await assert.rejects(huge.request({op:'test'}), /exceeds 16 MiB/);
  } finally { clients.forEach(client => client.dispose()); await rm(temp, {recursive:true, force:true}); }
});
