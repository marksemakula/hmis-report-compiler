// Deletes the register extract from the Blob store once FastAPI has staged it
// in Postgres. Patient-level files should not linger in storage.
import { del } from '@vercel/blob';
import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { jwtVerify } from 'jose';

const BLOB_URL = /^https:\/\/[a-z0-9]+\.(private|public)\.blob\.vercel-storage\.com\//;

export async function POST(request) {
    try {
          const token = (await cookies()).get('hmis_token')?.value;
          if (!token) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
          const secret = new TextEncoder().encode(process.env.JWT_SECRET || 'change-me-in-production');
          await jwtVerify(token, secret, { algorithms: ['HS256'] });
          const { url } = await request.json();
          if (!url || !BLOB_URL.test(url)) {
                  return NextResponse.json({ error: 'Invalid blob URL' }, { status: 400 });
          }
          await del(url);
          return NextResponse.json({ deleted: true });
    } catch (error) {
          return NextResponse.json({ error: error.message }, { status: 400 });
    }
}
