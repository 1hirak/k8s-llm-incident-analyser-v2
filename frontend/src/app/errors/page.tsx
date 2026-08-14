import { Suspense } from "react";

import { ErrorsClient } from "./errors-client";

export default function ErrorsPage() {
  return (
    <Suspense fallback={null}>
      <ErrorsClient />
    </Suspense>
  );
}
