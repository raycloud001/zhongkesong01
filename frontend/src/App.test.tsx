import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { App } from './App';

describe('App', () => {
  it('renders the assessment entry content without a browser runtime', () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain('id="landing-title"');
    expect(html).toContain('把“我适合什么”');
    expect(html).toContain('开始正式测评');
    expect(html).toContain('查看演示报告');
  });

});
