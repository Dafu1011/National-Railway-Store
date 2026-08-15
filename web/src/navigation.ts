export type AppRoute = "/login" | "/generate";

export function pageForAuthState(token: string, currentPath: string): AppRoute {
  if (!token) {
    return "/login";
  }
  if (currentPath === "/login" || currentPath === "/") {
    return "/generate";
  }
  return "/generate";
}
