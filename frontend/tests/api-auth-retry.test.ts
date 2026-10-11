/** @jest-environment node */
import { apiFetch, authFetch } from '@/lib/api';
import { getSession, signOut } from 'next-auth/react';
import { reportIncident } from '@/lib/incidents';

jest.mock('next-auth/react', () => ({getSession:jest.fn(),signOut:jest.fn()}));
jest.mock('@/lib/incidents', () => ({reportIncident:jest.fn()}));
const session = getSession as jest.Mock;
const expired = () => new Response('{}', {status:401,headers:{'X-Request-ID':'original'}});

beforeEach(() => { jest.clearAllMocks(); global.fetch = jest.fn(); });

it('silently recovers concurrent expired requests through one shared refresh', async () => {
  let complete!: (value:any) => void;
  session.mockReturnValue(new Promise(resolve => { complete = resolve; }));
  (fetch as jest.Mock).mockImplementation(async (_url, init) =>
    new Headers(init.headers).get('Authorization') === 'Bearer fresh'
      ? new Response('{"ok":true}') : expired());
  const a = apiFetch('/private', {token:'old'});
  const b = authFetch('/upload', {token:'old'});
  await new Promise(resolve => setTimeout(resolve,0));
  expect(session).toHaveBeenCalledTimes(1);
  complete({access_token:'fresh'});
  expect(await a).toEqual({ok:true});
  expect((await b).status).toBe(200);
  const headers = (fetch as jest.Mock).mock.calls.map(args => new Headers(args[1].headers));
  expect(headers.map(h => h.get('X-Aoria-Auth-Retry'))).toEqual(['managed','managed',null,null]);
  expect(reportIncident).not.toHaveBeenCalled();
  expect(signOut).not.toHaveBeenCalled();
});

it.each(['missing','rejected','still-401'])('reports a terminal auth failure: %s', async (mode) => {
  if (mode === 'rejected') session.mockRejectedValue(new Error('private'));
  else session.mockResolvedValue(mode === 'missing' ? null : {access_token:'fresh'});
  (fetch as jest.Mock).mockResolvedValue(expired());
  await expect(apiFetch('/private', {token:'old'})).rejects.toThrow('Session expirée');
  expect(reportIncident).toHaveBeenCalledWith('http_error', {status:401,request_id:'original'});
  expect(signOut).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledTimes(mode === 'still-401' ? 2 : 1);
});
