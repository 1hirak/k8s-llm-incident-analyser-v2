export function register() {
  if (typeof process !== "undefined" && typeof process.on === "function") {
    process.on("uncaughtException", (error) => {
      console.error(JSON.stringify({ msg: "uncaught_exception", error: error.message, stack: error.stack }));
    });

    process.on("unhandledRejection", (reason) => {
      console.error(JSON.stringify({
        msg: "unhandled_rejection",
        error: reason instanceof Error ? reason.message : String(reason),
      }));
    });
  }
}
