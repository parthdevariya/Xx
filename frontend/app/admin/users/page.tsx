"use client";

import { useState } from "react";
import { useAction } from "@/components/admin/common";
import { Badge, Button, Empty, ErrorNote, Field, Input, Modal, PageHeader, Panel, Select, Spinner, Table, Td, Toggle, fmtTime, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type U = { id: string; email: string; display_name: string; role: string; role_name: string; permissions: string[]; is_active: boolean; created_at: string; last_login_at: string | null };
type Role = { code: string; name: string; rank: number; permissions: string[] };

export default function UsersPage() {
  const { can, user: me } = useAuth();
  const write = can("users.write");
  const users = useAsync(() => api.get<U[]>("/users"));
  const roles = useAsync(() => api.get<Role[]>("/users/roles"));
  const [edit, setEdit] = useState<U | "new" | null>(null);
  const allPerms = Array.from(new Set((roles.data ?? []).flatMap((r) => r.permissions))).sort();
  return (
    <div className="space-y-4">
      <PageHeader title="Users & Access" subtitle="Role-based access control. Every protected operation is checked on the server."
        actions={write && <Button variant="primary" onClick={() => setEdit("new")}>Create user</Button>} />
      <ErrorNote error={users.error || roles.error} />
      <Panel title="Users">
        {users.loading && !users.data ? <Spinner /> : users.data && (users.data.length === 0 ? <Empty>No users.</Empty> : (
          <Table head={["User", "Role", "Status", "Created", "Last sign-in", ""]}>
            {users.data.map((u) => (
              <tr key={u.id}>
                <Td><div>{u.display_name || "—"}{u.id === me?.id && <Badge className="ml-2">you</Badge>}</div><div className="font-mono text-xs text-muted">{u.email}</div></Td>
                <Td>{u.role_name}</Td>
                <Td>{u.is_active ? <Badge tone="green">active</Badge> : <Badge tone="red">deactivated</Badge>}</Td>
                <Td className="text-xs">{fmtTime(u.created_at)}</Td>
                <Td className="text-xs">{fmtTime(u.last_login_at)}</Td>
                <Td>{write && <Button size="sm" variant="ghost" onClick={() => setEdit(u)}>Edit</Button>}</Td>
              </tr>
            ))}
          </Table>
        ))}
      </Panel>
      <Panel title="Roles & permissions">
        {roles.data && (
          <div className="overflow-x-auto rounded-md border border-line">
            <table className="w-full min-w-[720px] text-sm">
              <thead><tr><th className="x-label px-3 py-2 text-left font-normal">Permission</th>{roles.data.map((r) => <th key={r.code} className="x-label px-2 py-2 font-normal">{r.name}</th>)}</tr></thead>
              <tbody className="divide-y divide-line">
                {allPerms.map((p) => (
                  <tr key={p}><td className="px-3 py-1.5 font-mono text-xs">{p}</td>
                    {roles.data!.map((r) => <td key={r.code} className="text-center">{r.permissions.includes(p) ? <span className="text-green" aria-label="granted">●</span> : <span className="text-muted" aria-label="not granted">·</span>}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {edit && roles.data && <UserModal u={edit === "new" ? null : edit} roles={roles.data} onClose={() => setEdit(null)} onDone={() => { setEdit(null); users.reload(); }} />}
    </div>
  );
}

function UserModal({ u, roles, onClose, onDone }: { u: U | null; roles: Role[]; onClose: () => void; onDone: () => void }) {
  const act = useAction();
  const [f, setF] = useState({ email: u?.email ?? "", display_name: u?.display_name ?? "", role: u?.role ?? "standard", is_active: u?.is_active ?? true, password: "" });
  return (
    <Modal open onClose={onClose} title={u ? `Edit ${u.email}` : "Create user"}>
      <div className="space-y-3">
        {!u && <Field label="Email"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>}
        <Field label="Display name"><Input value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></Field>
        <Field label="Role" hint="You cannot assign a role equal to or above your own unless you are a Super Administrator."><Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} options={roles.map((r) => ({ value: r.code, label: r.name }))} /></Field>
        <Field label={u ? "Reset password (optional)" : "Password"} hint="At least 12 characters, mixed case, with a digit."><Input type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        {u && <Toggle checked={f.is_active} onChange={(v) => setF({ ...f, is_active: v })} label={f.is_active ? "Active" : "Deactivated (sessions revoked)"} />}
        <ErrorNote error={act.error} />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={act.busy === "s"} onClick={() => act.run("s", async () => {
            if (u) {
              const body: Record<string, unknown> = {};
              if (f.display_name !== u.display_name) body.display_name = f.display_name;
              if (f.role !== u.role) body.role = f.role;
              if (f.is_active !== u.is_active) body.is_active = f.is_active;
              if (f.password) body.password = f.password;
              await api.patch(`/users/${u.id}`, body);
            } else await api.post("/users", { email: f.email, display_name: f.display_name, role: f.role, password: f.password });
            onDone();
          })}>Save</Button></div>
      </div>
    </Modal>
  );
}
