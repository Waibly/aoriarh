export interface SessionUser {
  id: string;
  email: string;
  full_name: string;
  role: "admin" | "manager" | "user";
  access_token: string;
}
