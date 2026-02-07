import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const backendUrl = process.env.BACKEND_URL;
  const apiKey = process.env.API_KEY;
  const debug = process.env.NEXT_PUBLIC_DEBUG === "true";

  if (!backendUrl) {
    return NextResponse.json(
      { error: "BACKEND_URL not configured on server" },
      { status: 500 }
    );
  }
  if (!apiKey) {
    return NextResponse.json(
      { error: "API_KEY not configured on server" },
      { status: 500 }
    );
  }

  try {
    const body = await req.json();
    // console.log("[/api/process] Proxying to:", `${backendUrl}/process`);
    // console.log("[/api/process] Request body:", body);
    if (debug) {
      console.log("[/api/process] Proxying to:", `${backendUrl}/process`);
      console.log("[/api/process] Request body:", body);
    }

    const response = await fetch(`${backendUrl}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
      body: JSON.stringify(body),
    });

    const text = await response.text();
    // console.log("[/api/process] Backend status:", response.status);
    // console.log("[/api/process] Backend response:", text.substring(0, 500)); // Truncate for logging
    if (debug) {
      console.log("[/api/process] Backend status:", response.status);
      console.log("[/api/process] Backend response:", text.substring(0, 500));
    }

    // Parse as JSON if possible
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }

    return NextResponse.json(data, { status: response.status });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Unknown error";
    // console.error("[/api/process] Proxy error:", error);
    if (debug) console.error("[/api/process] Proxy error:", error);
    return NextResponse.json(
      { error: "Proxy request failed", detail: message },
      { status: 502 }
    );
  }
}
