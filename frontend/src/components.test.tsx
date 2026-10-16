import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { errorText } from './api'
import { OutfitPanel, PromptPanel, settingsSummary } from './components/panels'
import type { Frame } from './types'

describe('errorText', () => {
  it('formats FastAPI errors', () => {
    expect(errorText({ detail: 'だめです' }, 400)).toBe('だめです')
    expect(errorText({ detail: [{ loc: ['body', 'targets', 0, 'box'], msg: 'bad' }] }, 422)).toBe('targets.0.box: bad')
    expect(errorText(null, 500)).toMatch('HTTP 500')
  })
})

describe('panels', () => {
  const frames: Frame[] = [
    { id: 'a', box: [0, 0, 1, 1], ref: 0, outfit: 'b', detIndex: null },
    { id: 'b', box: [0, 0, 1, 1], ref: 1, outfit: 'a', detIndex: null },
  ]

  it('outfit toggles dispatch per frame', () => {
    const dispatch = vi.fn()
    render(<OutfitPanel frames={frames} dispatch={dispatch} />)
    const groups = screen.getAllByRole('group')
    expect(groups).toHaveLength(2)
    fireEvent.click(screen.getAllByText('A の服装のまま')[0])
    expect(dispatch).toHaveBeenCalledWith({ type: 'setOutfit', id: 'a', outfit: 'a' })
    // Grok の読み取りは準備中（無効）
    expect((screen.getByRole('checkbox') as HTMLInputElement).disabled).toBe(true)
  })

  it('prompt panel shows edited notice and reset', () => {
    const setOverride = vi.fn()
    const { rerender } = render(
      <PromptPanel auto="AUTO" override={null} setOverride={setOverride} warnings={[]} loading={false} error={null} />,
    )
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('AUTO')
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'EDITED' } })
    expect(setOverride).toHaveBeenCalledWith('EDITED')
    rerender(<PromptPanel auto="AUTO" override="EDITED" setOverride={setOverride} warnings={[]} loading={false} error={null} />)
    expect(screen.getByText(/自動生成を止めています/)).toBeTruthy()
    fireEvent.click(screen.getByText('自動生成に戻す'))
    expect(setOverride).toHaveBeenLastCalledWith(null)
  })

  it('settings summary', () => {
    expect(settingsSummary({ model: 'turbo', strength: 1, seed: null, count: 2 })).toBe('Turbo・強さ 1.00・2枚・シード ランダム')
  })
})
