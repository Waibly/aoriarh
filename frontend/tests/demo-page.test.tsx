import { render, screen, waitFor } from '@testing-library/react';
import DemoPage from '@/app/demo/page';
import { streamPublicAsk } from '@/lib/demo-api';

jest.mock('next/navigation', () => ({useSearchParams: () => new URLSearchParams('q=Question')}));
jest.mock('@/lib/demo-api', () => ({streamPublicAsk: jest.fn()}));
jest.mock('@/lib/gtag', () => ({trackDemoUtilisee: jest.fn()}));
jest.mock('@/components/demo/turnstile', () => ({TURNSTILE_ENABLED:false,Turnstile:()=>null}));
jest.mock('@/components/chat/search-details', () => ({SearchDetailsPanel:()=>null}));
jest.mock('@/components/chat/streaming-bubble', () => ({StreamingBubble: ({content}:{content:string}) => <pre data-testid="answer">{content}</pre>}));

test('keeps the original partial answer visible when the stream fails', async () => {
 const original = '  Réponse originale\n\n';
 (streamPublicAsk as jest.Mock).mockImplementation(async (_params, cb) => {
  cb.onDelta(original);
  cb.onError('Interruption technique');
 });
 render(<DemoPage />);
 await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Interruption technique'));
 expect(screen.getByTestId('answer').textContent).toBe(original);
 expect(screen.queryByText('Débloquez tout Aoria RH — gratuitement')).not.toBeInTheDocument();
 expect(streamPublicAsk).toHaveBeenCalledTimes(1);
});
