import express, { Request, Response, NextFunction } from "express";
import nodemailer from "nodemailer";
import { register, Counter, Histogram } from "prom-client";
import winston from "winston";
import { v4 as uuidv4 } from "uuid";

// --- Logger ---
const logger = winston.createLogger({
  level: "info",
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.json()
  ),
  defaultMeta: { service: "notification-service" },
  transports: [new winston.transports.Console()],
});

// --- Metrics ---
const httpRequestsTotal = new Counter({
  name: "http_requests_total",
  help: "Total HTTP requests",
  labelNames: ["method", "endpoint", "status_code"],
});
const emailsSentTotal = new Counter({
  name: "emails_sent_total",
  help: "Total emails sent",
});
const emailSendDuration = new Histogram({
  name: "email_send_duration_seconds",
  help: "Email send duration in seconds",
});

// --- Mail Transport ---
const transporter = nodemailer.createTransport({
  host: process.env.SMTP_HOST || "localhost",
  port: parseInt(process.env.SMTP_PORT || "1025"),
  secure: false,
});

// --- App ---
const app = express();
app.use(express.json());

// Request ID + logging middleware
app.use((req: Request, res: Response, next: NextFunction) => {
  const requestId = uuidv4();
  (req as any).requestId = requestId;
  res.setHeader("X-Request-ID", requestId);

  const start = Date.now();
  res.on("finish", () => {
    const duration = (Date.now() - start) / 1000;
    httpRequestsTotal.inc({
      method: req.method,
      endpoint: req.path,
      status_code: res.statusCode.toString(),
    });
    logger.info("request", {
      request_id: requestId,
      method: req.method,
      path: req.path,
      status: res.statusCode,
      duration_ms: duration * 1000,
    });
  });
  next();
});

// --- Routes ---

interface NotifyRequest {
  order_id: string;
  customer_email: string;
  customer_name: string;
  total_amount: number;
}

app.post("/notify", async (req: Request, res: Response) => {
  const body = req.body as NotifyRequest;

  if (!body.order_id || !body.customer_email) {
    res.status(400).json({ error: "order_id and customer_email are required" });
    return;
  }

  const timer = emailSendDuration.startTimer();
  try {
    const info = await transporter.sendMail({
      from: process.env.SMTP_FROM || "noreply@acmecorp.com",
      to: body.customer_email,
      subject: `Order Confirmation — ${body.order_id}`,
      html: `
        <h1>Thank you, ${body.customer_name}!</h1>
        <p>Your order <strong>${body.order_id}</strong> has been confirmed.</p>
        <p>Total: <strong>$${body.total_amount?.toFixed(2) || "0.00"}</strong></p>
        <p>We'll notify you when your order ships.</p>
      `,
    });

    emailsSentTotal.inc();
    timer();

    logger.info("email_sent", {
      order_id: body.order_id,
      to: body.customer_email,
      message_id: info.messageId,
    });

    res.json({ success: true, message_id: info.messageId });
  } catch (error: any) {
    timer();
    logger.error("email_failed", {
      order_id: body.order_id,
      error: error.message,
    });
    res.status(500).json({ success: false, error: error.message });
  }
});

app.get("/health", (_req: Request, res: Response) => {
  res.json({ status: "ok" });
});

app.get("/metrics", async (_req: Request, res: Response) => {
  res.set("Content-Type", register.contentType);
  res.end(await register.metrics());
});

// --- Start ---
const PORT = parseInt(process.env.PORT || "4003");
app.listen(PORT, () => {
  logger.info(`notification-service listening on port ${PORT}`);
});
