import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, refreshAccessToken, request, setAccessToken, setUnauthorizedHandler } from "../api/client";
import type { User } from "../api/types";
import { useQueryClient } from "@tanstack/react-query";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string, mfa?: string) => Promise<void>;
  logout: (reason?: string) => Promise<void>;
  can: (...perms: string[]) => boolean;
  hasRole: (...roles: string[]) => boolean;
  logoutReason: string | null;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [logoutReason, setLogoutReason] = useState<string | null>(null);
  const qc = useQueryClient();
  const idleTimer = useRef<number | null>(null);

  const loadMe = useCallback(async () => setUser(await api.get<User>("/users/me")), []);

  const logout = useCallback(async (reason?: string) => {
    try {
      await request("/auth/logout", { method: "POST" });
    } catch {
      /* ignore */
    }
    setAccessToken(null);
    setUser(null);
    qc.clear(); // no PHI kept in memory after logout
    setLogoutReason(reason ?? null);
  }, [qc]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAccessToken(null);
      setUser(null);
    });
    refreshAccessToken()
      .then(async (t) => (t ? loadMe() : undefined))
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, [loadMe]);

  // proactive token refresh (access tokens live 15 minutes)
  useEffect(() => {
    if (!user) return;
    const id = window.setInterval(() => refreshAccessToken(), 10 * 60 * 1000);
    return () => window.clearInterval(id);
  }, [user]);

  // auto-logout after inactivity (spec §13.3)
  useEffect(() => {
    if (!user) return;
    const minutes = user.idle_logout_minutes ?? 15;
    const reset = () => {
      if (idleTimer.current) window.clearTimeout(idleTimer.current);
      idleTimer.current = window.setTimeout(() => logout("You were signed out after a period of inactivity."), minutes * 60 * 1000);
    };
    const events = ["mousemove", "keydown", "click", "scroll"];
    events.forEach((e) => window.addEventListener(e, reset, { passive: true }));
    reset();
    return () => {
      events.forEach((e) => window.removeEventListener(e, reset));
      if (idleTimer.current) window.clearTimeout(idleTimer.current);
    };
  }, [user, logout]);

  const login = async (email: string, password: string, mfa?: string) => {
    const res = await api.post<{ access_token: string }>("/auth/login", { email, password, mfa_code: mfa || undefined });
    setAccessToken(res.access_token);
    setLogoutReason(null);
    await loadMe();
  };

  const can = (...perms: string[]) => !!user && perms.some((p) => user.permissions.includes(p));
  const hasRole = (...roles: string[]) => !!user && roles.some((r) => user.roles.includes(r));

  return <Ctx.Provider value={{ user, loading, login, logout, can, hasRole, logoutReason }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
