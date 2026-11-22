import express from 'express';
import pg from 'pg';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { onRequest } from '../dist/api/functions/api/[[path]].js';

const { Pool } = pg;
const pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 4, idleTimeoutMillis: 10_000, connectionTimeoutMillis: 15_000, ssl: process.env.DATABASE_URL?.includes('localhost') ? false : { rejectUnauthorized: false } });

class PgStatement {
  constructor(pool, sql, values = []) { this.pool = pool; this.sql = sql; this.values = values; }
  bind(...values) { this.values = values; return this; }
  query(client = this.pool) { return client.query(this.sql.replace(/\?/g, (_, offset) => `$${(this.sql.slice(0, offset).match(/\?/g) ?? []).length + 1}`), this.values); }
  async first() { return (await this.query()).rows[0] ?? null; }
  async all() { return { success: true, results: (await this.query()).rows }; }
  async run() { const result = await this.query(); return { success: true, results: result.rows, meta: { changes: result.rowCount ?? 0 } }; }
}
class PgDatabase {
  constructor(pool) { this.pool = pool; }
  prepare(sql) { return new PgStatement(this.pool, sql); }
  async batch(statements) {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      const results = [];
      for (const statement of statements) results.push(await statement.query(client));
      await client.query('COMMIT');
      return results;
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally { client.release(); }
  }
}
class PgMedia {
  constructor(pool) { this.pool = pool; }
  async get(key) {
    const { rows } = await this.pool.query('SELECT content,content_type FROM media_objects WHERE key=$1', [key]);
    const row = rows[0];
    if (!row) return null;
    const bytes = new Uint8Array(row.content);
    return { body: new ReadableStream({ start(controller) { controller.enqueue(bytes); controller.close(); } }), httpMetadata: { contentType: row.content_type }, httpEtag: `"${createHash('sha256').update(bytes).digest('hex')}"` };
  }
  async put(key, value, options = {}) {
    const bytes = Buffer.from(await new Response(value).arrayBuffer());
    await this.pool.query('INSERT INTO media_objects(key,content,content_type) VALUES($1,$2,$3) ON CONFLICT(key) DO UPDATE SET content=excluded.content,content_type=excluded.content_type', [key, bytes, options.httpMetadata?.contentType ?? 'application/octet-stream']);
  }
  async delete(key) { await this.pool.query('DELETE FROM media_objects WHERE key=$1', [key]); }
}

async function migrate() {
  for (const path of ['migrations/0001_initial.sql', 'migrations/0002_security.sql']) {
    await pool.query(await readFile(new URL(`../${path}`, import.meta.url), 'utf8'));
  }
}

const app = express();
app.disable('x-powered-by');
app.use((_req, res, next) => {
  res.set({
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'X-Frame-Options': 'DENY',
    'Strict-Transport-Security': 'max-age=31536000',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    'Content-Security-Policy': "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob: https:; connect-src 'self'; frame-src https://www.google.com https://maps.google.com"
  });
  next();
});
app.use('/api', express.raw({ type: () => true, limit: '6mb' }));
app.use('/api', async (req, res) => {
  try {
    const headers = new Headers();
    for (const [key, value] of Object.entries(req.headers)) {
      if (Array.isArray(value)) value.forEach(item => headers.append(key, item));
      else if (value !== undefined) headers.set(key, value);
    }
    const body = Buffer.isBuffer(req.body) && req.body.length ? new Uint8Array(req.body) : undefined;
    const request = new Request(`${req.protocol}://${req.get('host')}${req.originalUrl}`, { method: req.method, headers, body: ['GET', 'HEAD'].includes(req.method) ? undefined : body });
    const response = await onRequest({ request, env: { DB: new PgDatabase(pool), MEDIA: new PgMedia(pool), ADMIN_EMAIL: process.env.ADMIN_EMAIL, ADMIN_PASSWORD_HASH: process.env.ADMIN_PASSWORD_HASH, SESSION_SECRET: process.env.SESSION_SECRET, BUSINESS_NAME: 'Dipu Turf Champion' } });
    response.headers.forEach((value, key) => { if (key.toLowerCase() !== 'set-cookie') res.setHeader(key, value); });
    const cookies = response.headers.getSetCookie?.();
    if (cookies?.length) res.setHeader('Set-Cookie', cookies);
    res.status(response.status);
    if (!response.body) return res.end();
    res.send(Buffer.from(await response.arrayBuffer()));
  } catch (error) {
    console.error('Request failed', error);
    res.status(500).json({ error: 'Something went wrong. Please try again.' });
  }
});
app.use(express.static('dist', { maxAge: '1h', index: false }));
app.get(/.*/, (_req, res) => res.sendFile(fileURLToPath(new URL('../dist/index.html', import.meta.url))));

const port = Number(process.env.PORT ?? 3000);
await migrate();
app.listen(port, '0.0.0.0', () => console.log(`Dipu Turf Champion listening on ${port}`));
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, async () => { await pool.end(); process.exit(0); });
