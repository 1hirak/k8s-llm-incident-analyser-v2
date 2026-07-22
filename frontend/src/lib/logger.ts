type LogFn = (obj: Record<string, unknown>) => void;

interface Logger {
  info: LogFn;
  error: LogFn;
  warn: LogFn;
  debug: LogFn;
}

const log =
  (level: "info" | "error" | "warn" | "debug"): LogFn =>
  (obj: Record<string, unknown>) => {
    const msg = obj.msg as string | undefined;
    const rest = { ...obj };
    delete rest.msg;
    const meta = Object.keys(rest).length ? JSON.stringify(rest) : "";
    const line = [msg, meta].filter(Boolean).join(" ");
    console[level](line);
  };

export const logger: Logger = {
  info: log("info"),
  error: log("error"),
  warn: log("warn"),
  debug: log("debug"),
};
