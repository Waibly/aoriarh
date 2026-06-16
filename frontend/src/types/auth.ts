export interface SessionUser {
  id: string;
  email: string;
  full_name: string;
  role: "admin" | "manager" | "user";
  staff_role: "business" | "tech" | null;
  access_token: string;
}
