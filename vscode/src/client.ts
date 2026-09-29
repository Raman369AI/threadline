import {spawn, ChildProcessWithoutNullStreams} from 'node:child_process';
import {StringDecoder} from 'node:string_decoder';

type Pending = {resolve: (value: any) => void; reject: (error: Error) => void; timer: NodeJS.Timeout};

/** One isolated analyzer, with bounded JSON-lines framing and deterministic teardown. */
export class AnalyzerClient {
  private child: ChildProcessWithoutNullStreams;
  private pending = new Map<number, Pending>();
  private serial = 0;
  private buffer = '';
  private decoder = new StringDecoder('utf8');
  private failure?: Error;
  private stderr = '';
  constructor(python: string, runner: string, cwd: string, log: (text: string) => void) {
    this.child = spawn(python, ['-I', '-S', '-u', runner], {cwd, shell:false, windowsHide:true});
    this.child.stdout.on('data', (chunk: Buffer) => {
      this.buffer += this.decoder.write(chunk);
      let newline: number;
      while ((newline = this.buffer.indexOf('\n')) >= 0) {
        if (newline > 16 * 1024 * 1024) { this.fail(new Error('Analyzer response exceeds 16 MiB')); return; }
        const line = this.buffer.slice(0, newline); this.buffer = this.buffer.slice(newline + 1);
        try {
          const response = JSON.parse(line);
          const request = this.pending.get(response.id);
          if (!request) throw new Error('Unexpected analyzer response');
          this.pending.delete(response.id); clearTimeout(request.timer);
          if (typeof response.error === 'string') request.reject(new Error(response.error));
          else if ('result' in response) request.resolve(response.result);
          else { request.reject(new Error('Malformed analyzer response')); throw new Error('Malformed analyzer response'); }
        } catch (error) { this.fail(new Error(`Invalid analyzer output: ${String(error)}`)); return; }
      }
      if (this.buffer.length > 16 * 1024 * 1024) this.fail(new Error('Analyzer response exceeds 16 MiB'));
    });
    this.child.stderr.on('data', (chunk: Buffer) => { this.stderr = (this.stderr + chunk.toString()).slice(-4096); });
    this.child.stdin.on('error', error => this.fail(error));
    this.child.on('error', error => this.fail(new Error(`Cannot start Python: ${error.message}`)));
    this.child.on('close', code => {
      if (this.stderr) log(this.stderr);
      this.fail(new Error(`Threadline analyzer stopped (exit ${code}). ${this.stderr || 'Reopen the review to restart it.'}`));
    });
  }
  get pid(): number | undefined { return this.child.pid; }
  get stopped(): boolean { return !!this.failure; }
  request<T = any>(data: Record<string, unknown>, timeout = 180000): Promise<T> {
    if (this.failure) return Promise.reject(this.failure);
    if (this.pending.size >= 64) return Promise.reject(new Error('Too many pending analyzer requests'));
    const id = ++this.serial, frame = JSON.stringify({...data, id}) + '\n';
    if (Buffer.byteLength(frame) > 1024 * 1024) return Promise.reject(new Error('Analyzer request exceeds 1 MiB'));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => this.fail(new Error('Analysis timed out. Narrow the source roots, then reopen the review.')), timeout);
      this.pending.set(id, {resolve, reject, timer});
      this.child.stdin.write(frame);
    });
  }
  private fail(error: Error) {
    if (this.failure) return;
    this.failure = error;
    for (const request of this.pending.values()) { clearTimeout(request.timer); request.reject(error); }
    this.pending.clear(); this.buffer = ''; this.child.kill();
  }
  dispose() { this.fail(new Error('Threadline review closed')); }
}
