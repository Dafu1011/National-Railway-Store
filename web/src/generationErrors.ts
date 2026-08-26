import { userFacingErrorMessage } from "./userFacingErrors";

export function generationErrorMessage(error: unknown): string {
  return userFacingErrorMessage(error, "generation");
}
