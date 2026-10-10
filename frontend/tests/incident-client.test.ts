/** @jest-environment node */
import fs from "node:fs";
import vm from "node:vm";
import { randomUUID } from "node:crypto";

function runtime(fetcher: jest.Mock) {
  const handlers: Record<string, Function> = {};
  const saved = new Map<string,string>();
  const win: any = {fetch:fetcher,addEventListener:(name:string,fn:Function) => handlers[name]=fn,setInterval:jest.fn()};
  const sandbox: any = {window:win,document:{addEventListener:jest.fn()},location:{hostname:"app.aoriarh.fr",origin:"https://app.aoriarh.fr",href:"https://app.aoriarh.fr/demo?q=RH_SECRET",pathname:"/demo"},
    navigator:{onLine:true},crypto:{randomUUID},URL,AbortSignal,
    sessionStorage:{getItem:(key:string) => saved.get(key),setItem:(key:string,value:string) => saved.set(key,value)},
    setTimeout,clearTimeout,Date,JSON};
  vm.runInNewContext(fs.readFileSync("public/incident-client.js","utf8"),sandbox);
  return {win,handlers,sandbox};
}

it("reports errors without request body, query, error text or credentials", async () => {
  const fetcher = jest.fn(async (_url: string, _options?: any) => ({status:202,ok:true}));
  const {handlers} = runtime(fetcher);
  handlers.error({message:"RH_SECRET",error:Error("TOKEN_SECRET")});
  await new Promise(resolve => setTimeout(resolve,0));
  const request = JSON.parse(fetcher.mock.calls[0][1].body);
  expect(request.code).toBe("javascript_error");
  expect(request.location).toBe("/demo");
  expect(JSON.stringify(request)).not.toContain("SECRET");
  expect(fetcher.mock.calls[0][1].credentials).toBe("omit");
});

it("returns the original failed response and correlates its server request", async () => {
  const requestId = randomUUID();
  const response = {ok:false,status:500,headers:{get:() => requestId}};
  const fetcher = jest.fn(async (url:string, _options?: any) => url.includes('/telemetry/') ? {status:202,ok:true} : response);
  const {win} = runtime(fetcher);
  expect(await win.fetch("https://api.aoriarh.fr/api/v1/example")).toBe(response);
  await new Promise(resolve => setTimeout(resolve,0));
  const call = fetcher.mock.calls.find(args => String(args[0]).includes('/telemetry/'))!;
  expect(JSON.parse(call[1].body).request_id).toBe(requestId);
});

it("does not report explicit cancellation or third-party analytics requests", async () => {
  const controller = new AbortController();
  controller.abort();
  const fetcher = jest.fn(async () => { throw controller.signal.reason; });
  const {win} = runtime(fetcher);
  await expect(win.fetch('/api/example',{signal:controller.signal})).rejects.toBeDefined();
  await expect(win.fetch('https://analytics.example/event')).rejects.toBeDefined();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("sends allowlisted technical reasons but never arbitrary error text", async () => {
  const fetcher = jest.fn(async (_url:string,_options?:any)=>({status:202,ok:true}));
  const {win}=runtime(fetcher);
  win.aoriaReportIncident('stream_error',{reason:'provider_quota_exhausted'});
  win.aoriaReportIncident('stream_error',{reason:'PRIVATE_MESSAGE'});
  await new Promise(resolve=>setTimeout(resolve,0));
  const sent=fetcher.mock.calls.map(args=>JSON.parse(args[1].body));
  expect(sent[0].reason).toBe('provider_quota_exhausted');
  expect(sent[1]).not.toHaveProperty('reason');
  expect(JSON.stringify(sent)).not.toContain('PRIVATE_MESSAGE');
});
