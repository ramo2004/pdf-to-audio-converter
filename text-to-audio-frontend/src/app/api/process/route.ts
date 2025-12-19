import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const backendUrl = process.env.BACKEND_URL;

  if (!backendUrl) {
    return NextResponse.json(
      { error: "BACKEND_URL not configured on server" },
      { status: 500 }
    );
  }

  try {
    const body = await req.json();
    console.log("[/api/process] Proxying to:", `${backendUrl}/process`);
    console.log("[/api/process] Request body:", body);

    const response = await fetch(`${backendUrl}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const text = await response.text();
    console.log("[/api/process] Backend status:", response.status);
    console.log("[/api/process] Backend response:", text.substring(0, 500)); // Truncate for logging

    // Parse as JSON if possible
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }

    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    console.error("[/api/process] Proxy error:", error);
    return NextResponse.json(
      { error: "Proxy request failed", detail: error.message },
      { status: 502 }
    );
  }
}
