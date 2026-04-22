describe('Customer Home', () => {
  beforeEach(() => {
    cy.seedProduct('HOME-001', '首页测试产品');
  });

  it('shows assessment CTA and hot products when not assessed', () => {
    cy.intercept('GET', /\/customers\/.+\/assessments/, { body: [] }).as('assessments');
    cy.visit('/');
    cy.wait('@assessments');
    cy.contains('不知道该买什么理财产品');
    cy.contains('开始风险评估');
    cy.contains('热门产品');
    cy.contains('首页测试产品');
    cy.contains('为您推荐').should('not.exist');
  });

  it('auto-creates anonymous customer only once', () => {
    cy.intercept('POST', '/api/v1/auth/customer/anonymous').as('createCustomer');
    cy.visit('/');
    cy.window().its('localStorage').invoke('getItem', 'customer_code')
      .should('match', /^CUS-/);
    cy.get('@createCustomer.all').should('have.length', 1);
  });

  it('recovers from stale customer_code in localStorage', () => {
    window.localStorage.setItem('customer_code', 'CUS-STALE-999');
    cy.intercept('POST', '/api/v1/auth/customer/anonymous').as('createCustomer');
    cy.visit('/');
    cy.wait('@createCustomer');
    cy.window().its('localStorage').invoke('getItem', 'customer_code')
      .should('match', /^CUS-/)
      .and('not.eq', 'CUS-STALE-999');
  });

  it('navigates to product detail from hot list', () => {
    cy.intercept('GET', /\/customers\/.+\/assessments/, { body: [] });
    cy.visit('/');
    cy.contains('首页测试产品').click();
    cy.url().should('include', '/products/HOME-001');
  });

  it('shows recommendations + hot products when assessed, with dedup', () => {
    cy.intercept('GET', /\/customers\/.+\/assessments/, {
      body: [
        {
          code: 'AS-1',
          source: 'questionnaire',
          risk_preference: 'C3',
          risk_label: '平衡型',
          ai_summary: null,
          created_at: '2025-01-01T00:00:00Z',
        },
      ],
    }).as('assessments');

    cy.intercept('GET', /\/recommendations/, {
      body: {
        risk_preference: 'C3',
        risk_label: '平衡型',
        exact_matches: [
          {
            product_code: 'HOME-001',
            name: '首页测试产品',
            type: '债券',
            expected_return: 4.5,
            risk_level: 'R3',
            match_type: 'exact',
          },
        ],
        adjacent_matches: [],
      },
    }).as('recs');

    cy.visit('/');
    cy.wait(['@assessments', '@recs']);

    cy.contains('当前风险偏好');
    cy.contains('平衡型');
    cy.contains('重新评估');
    cy.contains('开始风险评估').should('not.exist');

    cy.contains('为您推荐');
    cy.contains('热门产品');

    // Dedup: HOME-001 appears under 为您推荐 but not twice.
    cy.get('body').contains('首页测试产品').should('have.length.at.least', 1);
    cy.contains('首页测试产品')
      .parentsUntil('body')
      .then(() => {
        cy.get(':contains("首页测试产品")').then(($els) => {
          // Ant Design Card nests text nodes; count distinct card wrappers
          const cards = Cypress.$($els).closest('.ant-card').toArray();
          const uniq = new Set(cards.map((c) => c));
          expect(uniq.size).to.eq(1);
        });
      });
  });

  it('shows empty-state hint when assessed but no recommended products', () => {
    cy.intercept('GET', /\/customers\/.+\/assessments/, {
      body: [
        {
          code: 'AS-2',
          source: 'questionnaire',
          risk_preference: 'C5',
          risk_label: '激进型',
          ai_summary: null,
          created_at: '2025-01-01T00:00:00Z',
        },
      ],
    });
    cy.intercept('GET', /\/recommendations/, {
      body: {
        risk_preference: 'C5',
        risk_label: '激进型',
        exact_matches: [],
        adjacent_matches: [],
      },
    });

    cy.visit('/');
    cy.contains('暂无合适的理财产品，建议查看热门产品或联系理财经理');
    cy.contains('热门产品');
  });

  it('re-assess button navigates to assessment page', () => {
    cy.intercept('GET', /\/customers\/.+\/assessments/, {
      body: [
        {
          code: 'AS-3',
          source: 'questionnaire',
          risk_preference: 'C3',
          risk_label: '平衡型',
          ai_summary: null,
          created_at: '2025-01-01T00:00:00Z',
        },
      ],
    });
    cy.intercept('GET', /\/recommendations/, {
      body: { risk_preference: 'C3', risk_label: '平衡型', exact_matches: [], adjacent_matches: [] },
    });
    cy.visit('/');
    cy.contains('重新评估').click();
    cy.url().should('include', '/assessment');
  });
});
