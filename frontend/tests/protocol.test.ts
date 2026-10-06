// @vitest-environment node
import { createServer } from 'node:http';
import type { RequestListener } from 'node:http';
import { describe, expect, it } from 'vitest';
import { ApiClient } from '../src/api/client';
import { decodeHealth, decodeJob, decodeProject, decodeResults } from '../src/api/decoders';
import { health, job, project, results, session } from './fixtures';
import { descriptorSummary, predictionSummary } from './descriptor-fixtures';
import { effectiveProperty } from '../src/model/propertyValues';
import { admet } from './analysis-fixtures';
import { decodeAdmet } from '../src/api/analysisDecoders';

async function withServer(
  handler: RequestListener,
  run: (client: ApiClient) => Promise<void>,
  timeout = 1000,
) {
  const server = createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Missing local test server address');
  const transport: typeof fetch = (input, init) =>
    fetch(`http://127.0.0.1:${address.port}${String(input)}`, init);
  try {
    await run(new ApiClient(transport, timeout));
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  }
}

describe('native HTTP client protocol (test-only controlled service, not backend acceptance)', () => {
  it('reads producer-owned order, waits and independent descriptors through native HTTP', async () => {
    const current = {
      ...job,
      stage_order: [
        'classify',
        'locate',
        'structures',
        'bind',
        'activity',
        'smiles',
        'final',
        'qa',
      ],
      stages: job.stages.map((stage, index) =>
        index === 0
          ? {
              ...stage,
              resource_wait: {
                reason: 'memory',
                required_mb: 2048,
                available_mb: 512,
                waited_seconds: 12,
              },
            }
          : stage,
      ),
    };
    const payload = {
      ...results,
      items: results.items.map((item) => ({
        ...item,
        descriptors: descriptorSummary,
        admet: {
          ...predictionSummary,
          status: 'failed',
          properties: [],
          error: { code: 'model_failed', message: 'LogS failed' },
        },
      })),
    };
    await withServer(
      (request, response) => {
        response.setHeader('Content-Type', 'application/json');
        response.end(
          JSON.stringify(
            request.url === '/api/v1/session'
              ? session
              : request.url === '/api/v1/jobs/current'
                ? current
                : payload,
          ),
        );
      },
      async (client) => {
        expect(await client.get('/jobs/current', decodeJob)).toEqual(current);
        const rows = await client.get('/projects/project-contract/results', decodeResults);
        expect(rows).toEqual(payload);
        expect(effectiveProperty(rows.items[0]!, 'molecular_weight')).toEqual({
          value: 46.069,
          manual: false,
        });
        expect(effectiveProperty(rows.items[0]!, 'Solubility_AqSolDB')).toEqual({
          value: null,
          manual: false,
        });
      },
    );
  });
  it('reads additive recognition and digest-addressed redraw through native HTTP and the production decoder', async () => {
    const payload = {
      ...results,
      items: results.items.map((item) => ({
        ...item,
        smiles: 'CCO',
        redraw_image_url:
          '/api/v1/projects/project-contract/structures/I-7/redraw?digest=protocol-only',
        recognition: {
          status: 'valid',
          quality_flag: null,
          model_fingerprint: 'protocol-only-model',
          token_confidence: { minimum: 0.4, mean: 0.8 },
        },
      })),
    };
    await withServer(
      (request, response) => {
        response.setHeader('Content-Type', 'application/json');
        response.end(JSON.stringify(request.url === '/api/v1/session' ? session : payload));
      },
      async (client) => {
        expect(await client.get('/projects/project-contract/results', decodeResults)).toEqual({
          ...payload,
          items: payload.items.map((item) => ({
            ...item,
            recognition: { ...item.recognition, stereochemistry: null },
          })),
        });
      },
    );
  });
  it('sends native JSON molecule inputs through CSRF and the actual analysis decoder', async () => {
    let payload: unknown;
    let csrf: string | undefined;
    await withServer(
      async (request, response) => {
        response.setHeader('Content-Type', 'application/json');
        if (request.url === '/api/v1/session') {
          response.end(JSON.stringify(session));
          return;
        }
        let raw = '';
        for await (const chunk of request) raw += String(chunk);
        payload = JSON.parse(raw) as unknown;
        csrf = request.headers['x-csrf-token'] as string | undefined;
        response.end(JSON.stringify(admet));
      },
      async (client) => {
        expect(
          await client.mutate('/analysis/admet', 'POST', { smiles: ['CCO'] }, decodeAdmet, {
            timeoutMs: 190_000,
          }),
        ).toEqual(admet);
      },
    );
    expect(payload).toEqual({ smiles: ['CCO'] });
    expect(csrf).toBe(session.csrf_token);
  });
  it('sends actual raw PDF bytes and CSRF over native fetch', async () => {
    let body = '';
    let csrf: string | undefined;
    let contentType: string | undefined;
    await withServer(
      async (request, response) => {
        response.setHeader('Content-Type', 'application/json');
        if (request.url === '/api/v1/session') {
          response.end(JSON.stringify(session));
          return;
        }
        csrf = request.headers['x-csrf-token'] as string | undefined;
        contentType = request.headers['content-type'];
        for await (const chunk of request) body += String(chunk);
        response.end(JSON.stringify(project));
      },
      async (client) => {
        expect(
          await client.upload(
            '/projects?filename=protocol.pdf',
            new File(['%PDF-1.7\nnative-bytes'], 'protocol.pdf'),
            decodeProject,
          ),
        ).toEqual(project);
      },
    );
    expect(body).toBe('%PDF-1.7\nnative-bytes');
    expect(contentType).toBe('application/pdf');
    expect(csrf).toBe(session.csrf_token);
  });
  it('aborts a real stalled response after headers without retrying a stale read', async () => {
    let requests = 0;
    let received!: () => void;
    const ready = new Promise<void>((resolve) => {
      received = resolve;
    });
    await withServer(
      (_request, response) => {
        requests++;
        response.writeHead(200, { 'Content-Type': 'application/json' });
        response.flushHeaders();
        received();
      },
      async (client) => {
        const controller = new AbortController();
        const read = client.get('/health', decodeHealth, controller.signal);
        const assertion = expect(read).rejects.toMatchObject({ name: 'AbortError' });
        await ready;
        controller.abort();
        await assertion;
      },
    );
    expect(requests).toBe(1);
  });
  it('times out a real write response and reports an uncertain result without replay', async () => {
    let writes = 0;
    await withServer(
      (request, response) => {
        response.writeHead(200, { 'Content-Type': 'application/json' });
        if (request.url === '/api/v1/session') response.end(JSON.stringify(session));
        else {
          writes++;
          response.flushHeaders();
        }
      },
      async (client) => {
        await expect(
          client.mutate('/projects/id/jobs', 'POST', {}, decodeProject),
        ).rejects.toMatchObject({ uncertain: true, code: 'timeout' });
      },
      75,
    );
    expect(writes).toBe(1);
  });
  it('decodes a native response through the same production adapter', async () => {
    await withServer(
      (_request, response) => {
        response.writeHead(200, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify(health));
      },
      async (client) => {
        expect(await client.get('/health', decodeHealth)).toEqual(health);
      },
    );
  });
});
