// Token exchange for client uploads to the private "hmis-uploads" Blob store.
// The browser calls this via upload() from @vercel/blob/client; the file goes
// browser -> Vercel Blob directly, bypassing the 4.5 MB function payload limit.
import { handleUpload } from '@vercel/blob/client';
import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { jwtVerify } from 'jose';

async function requireDataOfficer() {
    const token = (await cookies()).get('hmis_token')?.value;
    if (!token) throw new Error('Not authenticated');
    const secret = new TextEncoder().encode(process.env.JWT_SECRET || 'change-me-in-production');
    const { payload } = await jwtVerify(token, secret, { algorithms: ['HS256'] });
    if (payload.role !== 'data_officer' && payload.role !== 'admin') {
          throw new Error('Not authorized to upload');
    }
}

export async function POST(request) {
    const body = await request.json();
    try {
          const jsonResponse = await handleUpload({
                  body,
                  request,
                  onBeforeGenerateToken: async () => {
                            await requireDataOfficer(); // without this, anyone could upload
                    return {
                                access: 'private',
                                allowedContentTypes: [
                                              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                              'application/vnd.ms-excel',
                                              'text/csv',
                                              'application/octet-stream',
                                            ],
                                maximumSizeInBytes: 25 * 1024 * 1024,
                                addRandomSuffix: true,
                    };
                  },
                  onUploadCompleted: async () => {
                            // Fires on deployed environments only (Vercel cannot reach localhost).
                    // Ingestion is driven by the frontend, so nothing is required here.
                  },
          });
          return NextResponse.json(jsonResponse);
    } catch (error) {
          return NextResponse.json({ error: error.message }, { status: 400 });
    }
}
