interface D1Result<T = Record<string, unknown>> { success: boolean; results: T[]; meta?: { changes?: number } }
interface D1Statement { bind(...values: unknown[]): D1Statement; first<T = Record<string, unknown>>(): Promise<T | null>; all<T = Record<string, unknown>>(): Promise<D1Result<T>>; run(): Promise<D1Result> }
interface D1Database { prepare(query: string): D1Statement; batch<T = unknown>(statements: D1Statement[]): Promise<T[]> }
interface R2Object { body: ReadableStream; httpMetadata?: { contentType?: string }; httpEtag?: string }
interface R2Bucket { get(key:string):Promise<R2Object|null>; put(key:string,value:ReadableStream|ArrayBuffer,options?:{httpMetadata?:{contentType?:string}}):Promise<unknown>; delete(key:string):Promise<void> }
interface Env { DB: D1Database; MEDIA?:R2Bucket; ADMIN_EMAIL?: string; ADMIN_PASSWORD_HASH?: string; SESSION_SECRET?: string; BUSINESS_NAME?: string }
interface BookingRow extends Record<string, unknown> {
  id: string; reference: string; name: string; phone: string; ground_id: string; play_date: string;
  start_time: string; end_time: string; total_amount: number; advance_amount: number; status: string;
  payment_status: string; payment_method: string; notes: string | null; created_at: string;
}

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff', 'referrer-policy': 'strict-origin-when-cross-origin' } });
const uuid = () => crypto.randomUUID();
const todayDhaka = () => { const p = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Dhaka', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date()); const v = Object.fromEntries(p.map(x => [x.type, x.value])); return `${v.year}-${v.month}-${v.day}`; };
const b64 = (value: ArrayBuffer | Uint8Array) => btoa(String.fromCharCode(...new Uint8Array(value instanceof ArrayBuffer ? value : value.buffer)));
const unb64 = (s: string) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const safeEqual = (a: Uint8Array, b: Uint8Array) => a.length === b.length && a.reduce((n, x, i) => n | (x ^ b[i]), 0) === 0;
const clientIp = (request: Request) => request.headers.get('cf-connecting-ip') ?? request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ?? 'unknown';

async function hmac(secret: string, message: string) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(message)));
}
async function allowPublicRequest(env: Env, request: Request, scope: string, limit: number, windowSeconds: number) {
  const ip = clientIp(request);
  const ipHash = b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(ip)));
  const now = Math.floor(Date.now() / 1000);
  const result = await env.DB.prepare(`INSERT INTO public_rate_limits(scope,ip_hash,requests,window_started_at) VALUES(?,?,1,?) ON CONFLICT(scope,ip_hash) DO UPDATE SET requests=CASE WHEN ?-window_started_at>=? THEN 1 ELSE requests+1 END,window_started_at=CASE WHEN ?-window_started_at>=? THEN ? ELSE window_started_at END RETURNING requests`)
    .bind(scope,ipHash,now,now,windowSeconds,now,windowSeconds,now).first<{requests:number}>();
  return (result?.requests ?? limit + 1) <= limit;
}
async function validPassword(password: string, encoded: string) {
  const [algorithm, iterationsRaw, saltRaw, hashRaw] = encoded.split('$');
  const iterations = Number(iterationsRaw);
  if (algorithm !== 'pbkdf2-sha256' || !Number.isInteger(iterations) || iterations < 100000 || iterations > 1000000 || !saltRaw || !hashRaw) return false;
  const keyMaterial = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveBits']);
  const derived = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: unb64(saltRaw), iterations }, keyMaterial, 256);
  return safeEqual(new Uint8Array(derived), unb64(hashRaw));
}
async function isAdmin(request: Request, env: Env) {
  if (!env.SESSION_SECRET) return false;
  const token = request.headers.get('cookie')?.split(';').map(v => v.trim()).find(v => v.startsWith('dtc_admin='))?.slice('dtc_admin='.length);
  if (!token) return false;
  const [body, signature] = token.split('.');
  if (!body || !signature) return false;
  try {
    const expected = await hmac(env.SESSION_SECRET, body);
    if (!safeEqual(expected, unb64(signature))) return false;
    const claims = JSON.parse(new TextDecoder().decode(unb64(body))) as { exp: number; email: string };
    return claims.exp > Date.now() && claims.email === env.ADMIN_EMAIL;
  } catch { return false; }
}
const cookie = (value: string, maxAge: number) => `dtc_admin=${value}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=${maxAge}`;
const validDate = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s) && s >= todayDhaka();
const timeMinutes = (s: string) => { const [h, m] = s.split(':').map(Number); return h * 60 + m; };
function makeReference() { const suffix=Array.from(crypto.getRandomValues(new Uint8Array(5)),v=>v.toString(16).padStart(2,'0')).join('').toUpperCase();return `DTC-${new Date().toISOString().slice(2, 10).replaceAll('-', '')}-${suffix}`; }
async function audit(env: Env, action: string, entityType: string, entityId: string | null, details: unknown) {
  await env.DB.prepare('INSERT INTO audit_log(id, action, entity_type, entity_id, details) VALUES(?,?,?,?,?)').bind(uuid(), action, entityType, entityId, JSON.stringify(details ?? {})).run();
}
async function notify(env: Env, type: string, bookingId: string, message: string) {
  await env.DB.prepare('INSERT INTO notifications(id,type,booking_id,message,channel,status) VALUES(?,?,?,?,?,?)').bind(uuid(), type, bookingId, message, 'in-app', 'queued').run();
}
async function slotIsOpen(env: Env, date: string, start: string, end: string, excludeId: string | null = null) {
  const existing = await env.DB.prepare(`SELECT id FROM bookings WHERE play_date=? AND status IN ('pending','confirmed','completed') AND start_time < ? AND end_time > ? AND (? IS NULL OR id<>?) LIMIT 1`).bind(date, end, start, excludeId, excludeId).first();
  if (existing) return false;
  const blocked = await env.DB.prepare(`SELECT id FROM blocked_slots WHERE play_date=? AND (start_time IS NULL OR (start_time < ? AND end_time > ?)) LIMIT 1`).bind(date, end, start).first();
  if (blocked) return false;
  const weekday = new Date(`${date}T12:00:00`).getDay();
  const hours = await env.DB.prepare('SELECT opens_at, closes_at, is_open FROM operating_hours WHERE weekday=?').bind(weekday).first<{opens_at:string;closes_at:string;is_open:number}>();
  return !!hours?.is_open && timeMinutes(start) >= timeMinutes(hours.opens_at) && timeMinutes(end) <= timeMinutes(hours.closes_at);
}
async function price(env: Env, date: string, start: string) {
  const p = await env.DB.prepare("SELECT * FROM pricing WHERE id='default'").first<{weekday_hourly:number;weekend_hourly:number;peak_hourly:number;peak_start:string;peak_end:string;advance_percent:number}>();
  if (!p) return null;
  const weekday = new Date(`${date}T12:00:00`).getDay();
  const base = weekday === 5 || weekday === 6 ? p.weekend_hourly : p.weekday_hourly;
  return { total: timeMinutes(start) >= timeMinutes(p.peak_start) && timeMinutes(start) < timeMinutes(p.peak_end) && p.peak_hourly > 0 ? p.peak_hourly : base, advancePercent: p.advance_percent };
}

export async function onRequest({ request, env }: { request: Request; env: Env }): Promise<Response> {
  const url = new URL(request.url); const path = url.pathname.replace(/^\/api\/?/, '').replace(/\/$/, '');
  const method = request.method.toUpperCase();
  if(path.startsWith('media/')&&method==='GET'){
    if(!env.MEDIA)return json({error:'Media storage is not configured'},503);
    const key=path.slice('media/'.length);if(!/^uploads\/[a-f0-9-]+\.(?:jpg|png|webp|avif)$/.test(key))return json({error:'Media not found'},404);
    const object=await env.MEDIA.get(key);if(!object)return json({error:'Media not found'},404);
    return new Response(object.body,{headers:{'content-type':object.httpMetadata?.contentType??'application/octet-stream','cache-control':'public, max-age=31536000, immutable','x-content-type-options':'nosniff','etag':object.httpEtag??''}});
  }
  if (method === 'OPTIONS') return new Response(null, { status: 204, headers: { 'access-control-allow-methods': 'GET,POST,PATCH,DELETE,OPTIONS', 'access-control-allow-headers': 'content-type' } });
  if (['POST', 'PATCH', 'DELETE'].includes(method)) {
    const origin = request.headers.get('origin');
    if (origin && new URL(origin).host !== url.host) return json({ error: 'Request origin rejected' }, 403);
  }
  try {
    if (path === 'health' && method === 'GET') return json({ ok: true, business: env.BUSINESS_NAME ?? 'Dipu Turf Champion' });

    if (path === 'auth/login' && method === 'POST') {
      if (!env.ADMIN_EMAIL || !env.ADMIN_PASSWORD_HASH || !env.SESSION_SECRET) return json({ error: 'Admin access is not configured yet' }, 503);
      const ip = clientIp(request);
      const ipHash = b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(ip)));
      const now = Math.floor(Date.now() / 1000);
      const attempt = await env.DB.prepare('SELECT attempts,window_started_at FROM login_attempts WHERE ip_hash=?').bind(ipHash).first<{attempts:number;window_started_at:number}>();
      if (attempt && now - attempt.window_started_at < 900 && attempt.attempts >= 8) return json({ error: 'Too many sign-in attempts. Try again in 15 minutes.' }, 429);
      const body = await request.json() as { email?: string; password?: string };
      const email = String(body.email ?? '').trim().toLowerCase();
      if (email !== env.ADMIN_EMAIL.toLowerCase() || !await validPassword(String(body.password ?? ''), env.ADMIN_PASSWORD_HASH)) {
        await env.DB.prepare(`INSERT INTO login_attempts(ip_hash,attempts,window_started_at) VALUES(?,1,?) ON CONFLICT(ip_hash) DO UPDATE SET attempts=CASE WHEN ?-window_started_at>=900 THEN 1 ELSE attempts+1 END,window_started_at=CASE WHEN ?-window_started_at>=900 THEN ? ELSE window_started_at END`).bind(ipHash,now,now,now,now).run();
        return json({ error: 'Email or password is incorrect' }, 401);
      }
      await env.DB.prepare('DELETE FROM login_attempts WHERE ip_hash=?').bind(ipHash).run();
      const claims = b64(new TextEncoder().encode(JSON.stringify({ email: env.ADMIN_EMAIL, exp: Date.now() + 8 * 60 * 60 * 1000 })));
      const token = `${claims}.${b64(await hmac(env.SESSION_SECRET, claims))}`;
      return new Response(JSON.stringify({ ok: true }), { headers: { 'content-type': 'application/json', 'set-cookie': cookie(token, 28800), 'cache-control': 'no-store' } });
    }
    if (path === 'auth/logout' && method === 'POST') return new Response(JSON.stringify({ ok: true }), { headers: { 'content-type': 'application/json', 'set-cookie': cookie('', 0) } });
    if (path === 'auth/me' && method === 'GET') { const authenticated = await isAdmin(request, env); return json({ authenticated, email: authenticated ? env.ADMIN_EMAIL : null }); }

    if (path === 'content' && method === 'GET') {
      const rows = await env.DB.prepare('SELECT key,value FROM website_content').all<{key:string;value:string}>();
      const content = Object.fromEntries(rows.results.map(r => [r.key, JSON.parse(r.value)]));
      return json({ content });
    }
    if (path === 'pricing' && method === 'GET') return json(await env.DB.prepare("SELECT * FROM pricing WHERE id='default'").first());

    if (path === 'availability' && method === 'GET') {
      const date = url.searchParams.get('date') ?? '';
      if (!validDate(date)) return json({ error: 'Choose a valid future date' }, 400);
      const weekday = new Date(`${date}T12:00:00`).getDay();
      const hours = await env.DB.prepare('SELECT opens_at,closes_at,is_open FROM operating_hours WHERE weekday=?').bind(weekday).first<{opens_at:string;closes_at:string;is_open:number}>();
      if (!hours?.is_open) return json({ date, slots: [] });
      const booked = await env.DB.prepare("SELECT start_time,end_time FROM bookings WHERE play_date=? AND status IN ('pending','confirmed','completed')").bind(date).all<{start_time:string;end_time:string}>();
      const blocked = await env.DB.prepare('SELECT start_time,end_time FROM blocked_slots WHERE play_date=?').bind(date).all<{start_time:string|null;end_time:string|null}>();
      const slots = [];
      for (let minute = timeMinutes(hours.opens_at); minute + 60 <= timeMinutes(hours.closes_at); minute += 60) {
        const start = `${String(Math.floor(minute/60)).padStart(2,'0')}:${String(minute%60).padStart(2,'0')}`;
        const endMin = minute + 60; const end = `${String(Math.floor(endMin/60)).padStart(2,'0')}:${String(endMin%60).padStart(2,'0')}`;
        const unavailable = booked.results.some(b => b.start_time < end && b.end_time > start) || blocked.results.some(b => !b.start_time || (!!b.end_time && b.start_time < end && b.end_time > start));
        const p = await price(env, date, start);
        slots.push({ start, end, available: !unavailable, amount: p?.total ?? 0 });
      }
      return json({ date, slots });
    }

    if (path === 'bookings' && method === 'POST') {
      if (!await allowPublicRequest(env,request,'booking-create',10,3600)) return json({error:'Too many booking requests. Please try again later.'},429);
      const body = await request.json() as { date?:string;time?:string;name?:string;phone?:string;notes?:string;paymentMethod?:string };
      const name = String(body.name ?? '').trim().slice(0, 100); const phone = String(body.phone ?? '').replace(/[^+\d]/g,'').slice(0, 18);
      const date = String(body.date ?? ''); const start = String(body.time ?? '');
      if (name.length < 2 || phone.length < 8 || phone.length > 18 || !validDate(date) || !/^([01]\d|2[0-3]):00$/.test(start)) return json({ error: 'Check your name, mobile number, date and time' }, 400);
      const endMins = timeMinutes(start) + 60; const end = `${String(Math.floor(endMins/60)).padStart(2,'0')}:${String(endMins%60).padStart(2,'0')}`;
      if (!await slotIsOpen(env, date, start, end)) return json({ error: 'That slot is no longer available' }, 409);
      const pricing = await price(env, date, start);
      if (!pricing || pricing.total <= 0) return json({ error: 'Booking is not open yet. Please contact the turf to confirm rates.' }, 503);
      const customerId = uuid(); const bookingId = uuid(); const reference = makeReference();
      const advance = Math.round(pricing.total * pricing.advancePercent / 100);
      const customer = env.DB.prepare(`INSERT INTO customers(id,name,phone) VALUES(?,?,?) ON CONFLICT(phone) DO UPDATE SET name=excluded.name` ).bind(customerId, name, phone);
      const booking = env.DB.prepare(`INSERT INTO bookings(id,reference,customer_id,ground_id,play_date,start_time,end_time,hours,total_amount,advance_amount,payment_method,notes) SELECT ?,?,id,'main',?,?,?,1,?,?,?,? FROM customers WHERE phone=?`)
        .bind(bookingId, reference, date, start, end, pricing.total, advance, String(body.paymentMethod ?? 'pay-at-turf').slice(0, 40), String(body.notes ?? '').trim().slice(0, 500) || null, phone);
      try { await env.DB.batch([customer, booking]); }
      catch { return json({ error: 'That slot was just booked. Choose another time.' }, 409); }
      await notify(env, 'new-booking', bookingId, `New booking ${reference} is waiting for review`);
      return json({ ok: true, reference, status: 'pending', amount: pricing.total, advance }, 201);
    }

    if (path === 'booking-lookup' && method === 'GET') {
      if (!await allowPublicRequest(env,request,'booking-lookup',30,3600)) return json({error:'Too many lookup attempts. Please try again later.'},429);
      const reference = (url.searchParams.get('reference') ?? '').trim().toUpperCase(); const phone = (url.searchParams.get('phone') ?? '').replace(/[^+\d]/g,'');
      if (!reference || phone.length < 8) return json({ error: 'Enter the booking reference and mobile number' }, 400);
      const booking = await env.DB.prepare(`SELECT b.reference,b.play_date,b.start_time,b.end_time,b.total_amount,b.advance_amount,b.status,b.payment_status,b.payment_method,c.name,c.phone FROM bookings b JOIN customers c ON c.id=b.customer_id WHERE b.reference=? AND c.phone=?`).bind(reference,phone).first();
      return booking ? json({ booking }) : json({ error: 'No booking matched those details' }, 404);
    }

    if (!await isAdmin(request, env)) return json({ error: 'Admin sign-in required' }, 401);

    if(path==='admin/media'&&method==='POST'){
      if(!env.MEDIA)return json({error:'Image storage is not configured yet'},503);
      const form=await request.formData();const file=form.get('file');if(!(file instanceof File))return json({error:'Choose an image first'},400);
      const extensions:Record<string,string>={'image/jpeg':'jpg','image/png':'png','image/webp':'webp','image/avif':'avif'};const ext=extensions[file.type];
      if(!ext)return json({error:'Upload a JPG, PNG, WebP or AVIF image'},415);if(file.size===0||file.size>5*1024*1024)return json({error:'Image size must be between 1 byte and 5 MB'},413);
      const key=`uploads/${uuid()}.${ext}`;await env.MEDIA.put(key,file.stream(),{httpMetadata:{contentType:file.type}});await audit(env,'image-uploaded','media',key,{type:file.type,size:file.size});
      return json({ok:true,url:`/api/media/${key}`},201);
    }
    if(path==='admin/media'&&method==='DELETE'){
      if(!env.MEDIA)return json({error:'Image storage is not configured yet'},503);const key=url.searchParams.get('key')??'';
      if(!/^uploads\/[a-f0-9-]+\.(?:jpg|png|webp|avif)$/.test(key))return json({error:'Media not found'},404);await env.MEDIA.delete(key);await audit(env,'image-deleted','media',key,{});return json({ok:true});
    }

    if (path === 'admin/overview' && method === 'GET') {
      const today = todayDhaka(); const month = today.slice(0, 7);
      const trendStart = new Date(`${today}T12:00:00Z`); trendStart.setUTCDate(trendStart.getUTCDate()-6); const trendFrom = trendStart.toISOString().slice(0,10);
      const [todayStats, pending, monthRevenue, customers, upcoming, recent, trend, peak] = await Promise.all([
        env.DB.prepare("SELECT COUNT(*) AS count,COALESCE(SUM(CASE WHEN payment_status='paid' THEN total_amount WHEN payment_status='partial' THEN advance_amount ELSE 0 END),0) AS revenue FROM bookings WHERE play_date=?").bind(today).first(),
        env.DB.prepare("SELECT COUNT(*) AS count FROM bookings WHERE status='pending'").first(),
        env.DB.prepare("SELECT COALESCE(SUM(CASE WHEN payment_status='paid' THEN total_amount WHEN payment_status='partial' THEN advance_amount ELSE 0 END),0) AS revenue FROM bookings WHERE play_date LIKE ?").bind(`${month}%`).first(),
        env.DB.prepare('SELECT COUNT(*) AS count FROM customers').first(),
        env.DB.prepare(`SELECT b.reference,b.play_date,b.start_time,b.total_amount,b.status,b.notes,c.name,c.phone FROM bookings b JOIN customers c ON c.id=b.customer_id WHERE b.play_date>=? AND b.status IN ('pending','confirmed') ORDER BY b.play_date,b.start_time LIMIT 8`).bind(today).all(),
        env.DB.prepare(`SELECT b.reference,b.play_date,b.start_time,b.total_amount,b.status,b.payment_status,c.name,c.phone FROM bookings b JOIN customers c ON c.id=b.customer_id ORDER BY b.created_at DESC LIMIT 40`).all()
        ,env.DB.prepare(`SELECT play_date,COUNT(*) AS count,COALESCE(SUM(CASE WHEN payment_status='paid' THEN total_amount WHEN payment_status='partial' THEN advance_amount ELSE 0 END),0) AS collected FROM bookings WHERE play_date>=? AND play_date<=? GROUP BY play_date ORDER BY play_date`).bind(trendFrom,today).all()
        ,env.DB.prepare(`SELECT start_time,COUNT(*) AS count FROM bookings WHERE play_date>=? AND status IN ('pending','confirmed','completed') GROUP BY start_time ORDER BY count DESC LIMIT 5`).bind(today).all()
      ]);
      return json({ today: todayStats, pending, month: monthRevenue, customers, upcoming: upcoming.results, bookings: recent.results, trend:trend.results, peak:peak.results });
    }
    if (path === 'admin/bookings' && method === 'GET') {
      const q = (url.searchParams.get('q') ?? '').trim().slice(0,100); const status = url.searchParams.get('status'); const date = url.searchParams.get('date');
      const rows = await env.DB.prepare(`SELECT b.*,c.name,c.phone FROM bookings b JOIN customers c ON c.id=b.customer_id WHERE (?='' OR c.name LIKE '%'||?||'%' OR c.phone LIKE '%'||?||'%' OR b.reference LIKE '%'||?||'%') AND (? IS NULL OR b.status=?) AND (? IS NULL OR b.play_date=?) ORDER BY b.play_date DESC,b.start_time DESC LIMIT 300`)
        .bind(q,q,q,q,status,status,date,date).all<BookingRow>();
      return json({ bookings: rows.results });
    }
    if (path === 'admin/calendar' && method === 'GET') {
      const date=url.searchParams.get('date')??todayDhaka();const mode=url.searchParams.get('mode')??'week';
      if(!/^\d{4}-\d{2}-\d{2}$/.test(date)||!['day','week','month'].includes(mode))return json({error:'Choose a valid calendar date and view'},400);
      const anchor=new Date(`${date}T12:00:00Z`);let from=date;let to=date;
      if(mode==='week'){anchor.setUTCDate(anchor.getUTCDate()-anchor.getUTCDay());from=anchor.toISOString().slice(0,10);anchor.setUTCDate(anchor.getUTCDate()+6);to=anchor.toISOString().slice(0,10)}
      if(mode==='month'){from=`${date.slice(0,7)}-01`;to=`${date.slice(0,7)}-${new Date(Date.UTC(anchor.getUTCFullYear(),anchor.getUTCMonth()+1,0)).getUTCDate().toString().padStart(2,'0')}`}
      const rows=await env.DB.prepare(`SELECT b.reference,b.play_date,b.start_time,b.end_time,b.total_amount,b.advance_amount,b.status,b.payment_status,b.notes,c.name,c.phone FROM bookings b JOIN customers c ON c.id=b.customer_id WHERE b.play_date>=? AND b.play_date<=? ORDER BY b.play_date,b.start_time LIMIT 500`).bind(from,to).all();
      return json({from,to,bookings:rows.results});
    }
    if (path === 'admin/bookings.csv' && method === 'GET') {
      const rows = await env.DB.prepare('SELECT b.reference,b.play_date,b.start_time,b.end_time,c.name,c.phone,b.total_amount,b.advance_amount,b.payment_status,b.status FROM bookings b JOIN customers c ON c.id=b.customer_id ORDER BY b.play_date DESC').all<Record<string,unknown>>();
      const cols = ['reference','play_date','start_time','end_time','name','phone','total_amount','advance_amount','payment_status','status'];
      const csv = [cols.join(','), ...rows.results.map(r => cols.map(k => `"${String(r[k] ?? '').replaceAll('"','""')}"`).join(','))].join('\r\n');
      return new Response(csv,{headers:{'content-type':'text/csv; charset=utf-8','content-disposition':'attachment; filename="dipu-bookings.csv"','cache-control':'no-store'}});
    }
    if (path === 'admin/customers.csv' && method === 'GET') {
      const rows=await env.DB.prepare(`SELECT c.name,c.phone,c.created_at,COUNT(b.id) AS bookings,COALESCE(SUM(CASE WHEN b.payment_status='paid' THEN b.total_amount WHEN b.payment_status='partial' THEN b.advance_amount ELSE 0 END),0) AS total_spend FROM customers c LEFT JOIN bookings b ON b.customer_id=c.id GROUP BY c.id ORDER BY c.created_at DESC`).all<Record<string,unknown>>();
      const cols=['name','phone','created_at','bookings','total_spend'];const csv=[cols.join(','),...rows.results.map(r=>cols.map(k=>`"${String(r[k]??'').replaceAll('"','""')}"`).join(','))].join('\r\n');
      return new Response(csv,{headers:{'content-type':'text/csv; charset=utf-8','content-disposition':'attachment; filename="dipu-customers.csv"','cache-control':'no-store'}});
    }
    if (path.startsWith('admin/bookings/') && method === 'PATCH') {
      const reference = path.split('/').pop()!; const body = await request.json() as {status?:string;paymentStatus?:string;transactionReference?:string};
      const validStatuses = ['pending','confirmed','rejected','cancelled','completed']; const validPayments = ['unpaid','partial','paid','refunded'];
      if (body.status && !validStatuses.includes(body.status) || body.paymentStatus && !validPayments.includes(body.paymentStatus)) return json({error:'Invalid status'},400);
      const existing = await env.DB.prepare('SELECT id,reference,status FROM bookings WHERE reference=?').bind(reference).first<{id:string;reference:string;status:string}>();
      if (!existing) return json({error:'Booking not found'},404);
      if (body.status) await env.DB.prepare('UPDATE bookings SET status=?,updated_at=CURRENT_TIMESTAMP WHERE reference=?').bind(body.status,reference).run();
      if (body.paymentStatus) {
        if (body.paymentStatus === 'paid' && (!String(body.transactionReference ?? '').trim() || (body as {verified?:boolean}).verified !== true)) return json({error:'Verify the payment with the provider and enter its transaction reference'},400);
        await env.DB.prepare('UPDATE bookings SET payment_status=?,transaction_reference=COALESCE(?,transaction_reference),updated_at=CURRENT_TIMESTAMP WHERE reference=?').bind(body.paymentStatus,String(body.transactionReference ?? '').trim() || null,reference).run();
      }
      const action = body.status ? `booking-${body.status}` : `payment-${body.paymentStatus}`;
      await audit(env,action,'booking',existing.id,body);
      if (body.status && ['confirmed','rejected','cancelled'].includes(body.status)) await notify(env,action,existing.id,`Booking ${reference} was ${body.status}`);
      return json({ok:true});
    }
    if (path.startsWith('admin/bookings/') && method === 'PUT') {
      const reference=path.split('/').pop()!;const body=await request.json() as {date?:string;time?:string;name?:string;phone?:string;notes?:string};
      const name=String(body.name??'').trim().slice(0,100);const phone=String(body.phone??'').replace(/[^+\d]/g,'').slice(0,18);const date=String(body.date??'');const start=String(body.time??'');
      if(name.length<2||phone.length<8||phone.length>18||!validDate(date)||!/^([01]\d|2[0-3]):00$/.test(start))return json({error:'Check the customer, date and time'},400);
      const existing=await env.DB.prepare('SELECT id,status FROM bookings WHERE reference=?').bind(reference).first<{id:string;status:string}>();
      if(!existing)return json({error:'Booking not found'},404);if(!['pending','confirmed'].includes(existing.status))return json({error:'Only pending or confirmed bookings can be edited'},409);
      const endMins=timeMinutes(start)+60;const end=`${String(Math.floor(endMins/60)).padStart(2,'0')}:${String(endMins%60).padStart(2,'0')}`;
      if(!await slotIsOpen(env,date,start,end,existing.id))return json({error:'That slot is unavailable'},409);
      const pricing=await price(env,date,start);if(!pricing||pricing.total<=0)return json({error:'Set a rate before editing this booking'},503);
      const newCustomerId=uuid();const customer=env.DB.prepare('INSERT INTO customers(id,name,phone) VALUES(?,?,?) ON CONFLICT(phone) DO UPDATE SET name=excluded.name').bind(newCustomerId,name,phone);
      const update=env.DB.prepare(`UPDATE bookings SET customer_id=(SELECT id FROM customers WHERE phone=?),play_date=?,start_time=?,end_time=?,total_amount=?,advance_amount=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?`).bind(phone,date,start,end,pricing.total,Math.round(pricing.total*pricing.advancePercent/100),String(body.notes??'').trim().slice(0,500)||null,existing.id);
      try{await env.DB.batch([customer,update])}catch{return json({error:'That slot was just booked. Choose another time.'},409)}
      await audit(env,'booking-edited','booking',existing.id,{date,start});return json({ok:true});
    }
    if (path === 'admin/bookings' && method === 'POST') {
      const body = await request.json() as {date?:string;time?:string;name?:string;phone?:string;notes?:string};
      const name=String(body.name??'').trim().slice(0,100);const phone=String(body.phone??'').replace(/[^+\d]/g,'').slice(0,18);const date=String(body.date??'');const start=String(body.time??'');
      if(name.length<2||phone.length<8||phone.length>18||!validDate(date)||!/^([01]\d|2[0-3]):00$/.test(start))return json({error:'Check the customer, date and time'},400);
      const endMins=timeMinutes(start)+60;const end=`${String(Math.floor(endMins/60)).padStart(2,'0')}:${String(endMins%60).padStart(2,'0')}`;
      if(!await slotIsOpen(env,date,start,end))return json({error:'That slot is unavailable'},409);
      const pricing=await price(env,date,start);if(!pricing||pricing.total<=0)return json({error:'Set a rate before creating a manual booking'},503);
      const customerId=uuid();const bookingId=uuid();const reference=makeReference();
      const customer=env.DB.prepare('INSERT INTO customers(id,name,phone) VALUES(?,?,?) ON CONFLICT(phone) DO UPDATE SET name=excluded.name').bind(customerId,name,phone);
      const booking=env.DB.prepare(`INSERT INTO bookings(id,reference,customer_id,ground_id,play_date,start_time,end_time,hours,total_amount,advance_amount,payment_method,status,notes) SELECT ?,?,id,'main',?,?,?,1,?,0,'cash','confirmed',? FROM customers WHERE phone=?`).bind(bookingId,reference,date,start,end,pricing.total,String(body.notes??'').slice(0,500)||null,phone);
      try{await env.DB.batch([customer,booking])}catch{return json({error:'That slot was just booked'},409)}
      await audit(env,'manual-booking-created','booking',bookingId,{reference,date,start});
      return json({ok:true,reference,status:'confirmed'},201);
    }
    if (path === 'admin/content' && method === 'PUT') {
      const content = await request.json() as Record<string, unknown>;
      const allowed = ['businessName','tagline','taglineBn','heroTitle','heroTitleBn','heroDescription','heroDescriptionBn','heroImage','about','aboutBn','phone','whatsapp','email','address','addressBn','mapsUrl','instagram','facebook','terms','privacy','facilities','facilitiesBn','gallery','testimonials'];
      const statements = Object.entries(content).filter(([key]) => allowed.includes(key)).map(([key,value]) => env.DB.prepare('INSERT INTO website_content(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP').bind(key,JSON.stringify(value)));
      if (!statements.length) return json({error:'No editable content supplied'},400);
      await env.DB.batch(statements); await audit(env,'website-content-updated','website',null,Object.keys(content)); return json({ok:true});
    }
    if (path === 'admin/pricing' && method === 'PUT') {
      const body = await request.json() as {weekday_hourly?:number;weekend_hourly?:number;peak_hourly?:number;peak_start?:string;peak_end?:string;advance_percent?:number};
      const vals = [body.weekday_hourly,body.weekend_hourly,body.peak_hourly].map(Number);
      if (vals.some(n => !Number.isSafeInteger(n) || n < 0 || n > 1000000) || !Number.isInteger(body.advance_percent) || Number(body.advance_percent) < 0 || Number(body.advance_percent) > 100 || !/^([01]\d|2[0-3]):00$/.test(body.peak_start??'') || !/^([01]\d|2[0-3]):00$/.test(body.peak_end??'') || timeMinutes(body.peak_end??'00:00')<=timeMinutes(body.peak_start??'23:00')) return json({error:'Check the pricing values'},400);
      await env.DB.prepare("UPDATE pricing SET weekday_hourly=?,weekend_hourly=?,peak_hourly=?,peak_start=?,peak_end=?,advance_percent=?,updated_at=CURRENT_TIMESTAMP WHERE id='default'").bind(...vals,body.peak_start,body.peak_end,body.advance_percent).run();
      await audit(env,'pricing-updated','pricing','default',body); return json({ok:true});
    }
    if (path === 'admin/hours' && method === 'GET') return json({hours:(await env.DB.prepare('SELECT * FROM operating_hours ORDER BY weekday').all()).results});
    if (path === 'admin/hours' && method === 'PUT') {
      const body = await request.json() as {hours?:Array<{weekday:number;opens_at:string;closes_at:string;is_open:boolean}>};
      if (!Array.isArray(body.hours) || body.hours.length !== 7 || new Set(body.hours.map(x=>x.weekday)).size !== 7 || body.hours.some(x=>!Number.isInteger(x.weekday)||x.weekday<0||x.weekday>6||!/^([01]\d|2[0-3]):00$/.test(x.opens_at)||!/^([01]\d|2[0-3]):00$/.test(x.closes_at)||timeMinutes(x.closes_at)<=timeMinutes(x.opens_at))) return json({error:'Set a valid open and close time for each day'},400);
      await env.DB.batch(body.hours.map(x=>env.DB.prepare('UPDATE operating_hours SET opens_at=?,closes_at=?,is_open=? WHERE weekday=?').bind(x.opens_at,x.closes_at,x.is_open?1:0,x.weekday)));
      await audit(env,'operating-hours-updated','availability',null,body.hours); return json({ok:true});
    }
    if (path === 'admin/blocks' && method === 'POST') {
      const body = await request.json() as {date?:string;start?:string|null;end?:string|null;reason?:string};
      if (!body.date || !validDate(body.date) || (!!body.start !== !!body.end) || body.start && (!/^([01]\d|2[0-3]):00$/.test(body.start) || !/^([01]\d|2[0-3]):00$/.test(body.end!))) return json({error:'Check the blocked date or time'},400);
      const id = uuid(); await env.DB.prepare('INSERT INTO blocked_slots(id,play_date,start_time,end_time,reason) VALUES(?,?,?,?,?)').bind(id,body.date,body.start??null,body.end??null,String(body.reason??'Unavailable').slice(0,160)).run();
      await audit(env,'slot-blocked','availability',id,body); return json({ok:true,id},201);
    }
    if (path === 'admin/blocks' && method === 'GET') return json({blocks:(await env.DB.prepare('SELECT * FROM blocked_slots WHERE play_date>=? ORDER BY play_date,start_time LIMIT 100').bind(todayDhaka()).all()).results});
    if (path === 'admin/blocks' && method === 'DELETE') {
      const id = url.searchParams.get('id'); if (!id) return json({error:'Block id required'},400);
      await env.DB.prepare('DELETE FROM blocked_slots WHERE id=?').bind(id).run(); await audit(env,'slot-unblocked','availability',id,{}); return json({ok:true});
    }
    if (path === 'admin/customers' && method === 'GET') {
      const rows = await env.DB.prepare(`SELECT c.id,c.name,c.phone,c.created_at,COUNT(b.id) AS bookings,COALESCE(SUM(CASE WHEN b.payment_status='paid' THEN b.total_amount WHEN b.payment_status='partial' THEN b.advance_amount ELSE 0 END),0) AS total_spend FROM customers c LEFT JOIN bookings b ON b.customer_id=c.id GROUP BY c.id ORDER BY c.created_at DESC LIMIT 500`).all(); return json({customers:rows.results});
    }
    if (path === 'admin/notifications' && method === 'GET') return json({notifications:(await env.DB.prepare('SELECT * FROM notifications ORDER BY created_at DESC LIMIT 50').all()).results});
    return json({ error: 'Not found' }, 404);
  } catch (error) {
    console.error('API error', error);
    return json({ error: 'Something went wrong. Please try again.' }, 500);
  }
}
