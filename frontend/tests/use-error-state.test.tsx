import { act, renderHook } from '@testing-library/react';
import { useErrorState } from '@/hooks/use-error-state';

test('rendering an already reported error does not create a duplicate alert', () => {
  const report=jest.fn();
  window.aoriaReportIncident=report;
  const {result}=renderHook(()=>useErrorState(''));
  act(()=>result.current[2]('Provider error'));
  expect(result.current[0]).toBe('Provider error');
  expect(report).not.toHaveBeenCalled();
  act(()=>result.current[1]('Unreported local error'));
  expect(result.current[0]).toBe('Unreported local error');
  expect(report).toHaveBeenCalledTimes(1);
  delete window.aoriaReportIncident;
});
