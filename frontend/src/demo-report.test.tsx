// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { App } from './App';

afterEach(() => cleanup());

describe('competition demo flow', () => {
  it('opens the demo report from the landing page', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: '查看演示报告' }));
    expect(await screen.findByRole('heading', { name: '你的职业行动地图' })).toBeTruthy();
    expect(screen.getByText('演示数据')).toBeTruthy();
  });

  it('shows unknown scores as waiting states without fake percentages', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: '查看演示报告' }));
    expect(await screen.findByText('评分方法待发布')).toBeTruthy();
    expect(screen.queryByText(/适配度\s*\d+%/)).toBeNull();
    expect(screen.getByText('暂不显示雷达、百分比或人才类型')).toBeTruthy();
  });
});
