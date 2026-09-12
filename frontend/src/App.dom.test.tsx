// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

afterEach(() => vi.restoreAllMocks());

describe('App landing flow', () => {
  it('starts the official assessment flow from the landing button', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
      const path=String(url);
      if(path.endsWith('/identity/anonymous')) return Promise.resolve(new Response(JSON.stringify({ownerId:'o',csrfToken:'c'}),{status:201}));
      if(path.includes('/sessions/current')) return Promise.resolve(new Response(JSON.stringify({session:null}),{status:200}));
      return Promise.resolve(new Response(JSON.stringify({id:'s',revision:0,status:'draft',questions:[],answers:[],demo:false}),{status:201}));
    });
    render(<App/>);
    fireEvent.click(screen.getByRole('button',{name:'开始正式测评'}));
    expect(await screen.findByText(/正在载入|暂时无法载入/)).toBeTruthy();
  });
});
