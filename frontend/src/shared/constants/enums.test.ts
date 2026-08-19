import { describe, expect, it } from 'vitest';
import {
  DEAL_STAGE,
  DEAL_STAGES,
  DEAL_STAGE_TRANSITIONS,
  INQUIRY_CATEGORIES,
  INQUIRY_CATEGORY,
  ORDER_STATUS,
  ORDER_STATUSES,
  ORDER_STATUS_TRANSITIONS,
  SHIPMENT_STATUS,
  SHIPMENT_STATUSES,
  STOCK_MOVEMENT_TYPE,
  STOCK_MOVEMENT_TYPES,
  isOrderEditable,
  statusMeta,
} from './enums';

describe('таблиця переходів угоди', () => {
  it('пропонує з ліда лише кваліфікацію', () => {
    expect(DEAL_STAGE_TRANSITIONS.LEAD).toEqual(['QUALIFIED']);
  });

  it('дає з пропозиції обидва результати — виграно й втрачено', () => {
    expect(DEAL_STAGE_TRANSITIONS.PROPOSAL).toEqual(['WON', 'LOST']);
  });

  it('нічого не пропонує з кінцевих стадій', () => {
    expect(DEAL_STAGE_TRANSITIONS.WON).toEqual([]);
    expect(DEAL_STAGE_TRANSITIONS.LOST).toEqual([]);
  });

  it('не дозволяє повернутися на попередню стадію', () => {
    expect(DEAL_STAGE_TRANSITIONS.QUALIFIED).not.toContain('LEAD');
    expect(DEAL_STAGE_TRANSITIONS.PROPOSAL).not.toContain('QUALIFIED');
  });

  // A target the table lists but the dictionary does not describe would render
  // the transition button with an empty caption.
  it('веде кожен перехід у стадію, яка сама є ключем таблиці й має підпис', () => {
    for (const stage of DEAL_STAGES) {
      for (const target of DEAL_STAGE_TRANSITIONS[stage]) {
        expect(DEAL_STAGE_TRANSITIONS[target]).toBeDefined();
        expect(DEAL_STAGE[target].label).not.toBe('');
      }
    }
  });

  it('описує кожну стадію зі списку', () => {
    for (const stage of DEAL_STAGES) {
      expect(DEAL_STAGE[stage].label).not.toBe('');
    }
  });

  it('досягає обох кінцевих стадій із ліда', () => {
    const reachable = new Set(['LEAD']);
    for (let step = 0; step < DEAL_STAGES.length; step += 1) {
      for (const stage of [...reachable]) {
        for (const target of DEAL_STAGE_TRANSITIONS[stage as (typeof DEAL_STAGES)[number]]) {
          reachable.add(target);
        }
      }
    }

    expect(reachable).toContain('WON');
    expect(reachable).toContain('LOST');
  });
});

describe('таблиця переходів замовлення', () => {
  it('дозволяє скасування з кожного робочого статусу', () => {
    expect(ORDER_STATUS_TRANSITIONS.DRAFT).toContain('CANCELLED');
    expect(ORDER_STATUS_TRANSITIONS.CONFIRMED).toContain('CANCELLED');
    expect(ORDER_STATUS_TRANSITIONS.PAID).toContain('CANCELLED');
  });

  it('нічого не пропонує з кінцевих статусів', () => {
    expect(ORDER_STATUS_TRANSITIONS.FULFILLED).toEqual([]);
    expect(ORDER_STATUS_TRANSITIONS.CANCELLED).toEqual([]);
  });

  it('не дає виконати замовлення, минаючи оплату', () => {
    expect(ORDER_STATUS_TRANSITIONS.DRAFT).not.toContain('FULFILLED');
    expect(ORDER_STATUS_TRANSITIONS.CONFIRMED).not.toContain('FULFILLED');
  });

  it('веде кожен перехід у статус, який сам є ключем таблиці й має підпис', () => {
    for (const status of ORDER_STATUSES) {
      for (const target of ORDER_STATUS_TRANSITIONS[status]) {
        expect(ORDER_STATUS_TRANSITIONS[target]).toBeDefined();
        expect(ORDER_STATUS[target].label).not.toBe('');
      }
    }
  });

  it('дозволяє редагувати лише чернетку', () => {
    expect(isOrderEditable('DRAFT')).toBe(true);
    for (const status of ORDER_STATUSES.filter((value) => value !== 'DRAFT')) {
      expect(isOrderEditable(status)).toBe(false);
    }
  });
});

describe('словники станів', () => {
  it('описує кожне значення всіх закритих списків', () => {
    for (const type of STOCK_MOVEMENT_TYPES) expect(STOCK_MOVEMENT_TYPE[type].label).not.toBe('');
    for (const status of SHIPMENT_STATUSES) expect(SHIPMENT_STATUS[status].label).not.toBe('');
    for (const category of INQUIRY_CATEGORIES)
      expect(INQUIRY_CATEGORY[category].label).not.toBe('');
  });

  it('має категорію для відповіді класифікатора поза списком', () => {
    expect(INQUIRY_CATEGORY.unknown.label).toBe('Не визначено');
  });
});

describe('statusMeta', () => {
  it('віддає підпис і колір відомого значення', () => {
    expect(statusMeta(DEAL_STAGE, 'WON')).toEqual({ label: 'Виграно', color: 'success' });
  });

  // The guard that keeps a state added on the server from rendering as a blank
  // tag: the raw value is worse than a label, but it is visible.
  it('віддає невідоме значення як його ж текст, а не порожнім', () => {
    expect(statusMeta(DEAL_STAGE, 'ON_HOLD')).toEqual({ label: 'ON_HOLD', color: 'default' });
  });

  it('не плутає порожній рядок із відсутнім значенням', () => {
    expect(statusMeta(ORDER_STATUS, '').label).toBe('');
  });

  it('не читає підпис із прототипу об’єкта', () => {
    expect(statusMeta(ORDER_STATUS, 'toString').label).toBe('toString');
  });
});
