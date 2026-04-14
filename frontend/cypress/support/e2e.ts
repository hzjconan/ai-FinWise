// Global Cypress support file

// Custom command: admin login via API and store token
Cypress.Commands.add('adminLogin', (username = 'admin', password = 'admin123') => {
  cy.request('POST', '/api/v1/auth/admin/login', { username, password }).then((resp) => {
    window.localStorage.setItem('admin_token', resp.body.access_token);
  });
});

// Custom command: create anonymous customer
Cypress.Commands.add('createAnonymousCustomer', () => {
  cy.request('POST', '/api/v1/auth/customer/anonymous').then((resp) => {
    window.localStorage.setItem('customer_code', resp.body.customer_code);
  });
});

// Custom command: seed a product via API (idempotent)
Cypress.Commands.add('seedProduct', (productCode: string, name: string) => {
  cy.request('POST', '/api/v1/auth/admin/login', {
    username: 'admin',
    password: 'admin123',
  }).then((loginResp) => {
    const token = loginResp.body.access_token;
    const headers = { Authorization: `Bearer ${token}` };

    // Check if product already exists
    cy.request({
      method: 'GET',
      url: `/api/v1/admin/products/${productCode}`,
      headers,
      failOnStatusCode: false,
    }).then((getResp) => {
      if (getResp.status === 200) {
        // Product already exists, just ensure it's active
        cy.request({
          method: 'PATCH',
          url: `/api/v1/admin/products/${productCode}/status`,
          body: { status: 'active' },
          headers,
          failOnStatusCode: false,
        });
        return;
      }

      // Create new product
      cy.request({
        method: 'POST',
        url: '/api/v1/admin/products',
        body: {
          product_code: productCode,
          name,
          type: '债券',
          min_investment: 10000,
        },
        headers,
      }).then(() => {
        const returns = [
          { period_label: '2024-Q1', return_rate: 4.1, recorded_at: '2024-03-31' },
          { period_label: '2024-Q2', return_rate: 4.35, recorded_at: '2024-06-30' },
          { period_label: '2024-Q3', return_rate: 4.5, recorded_at: '2024-09-30' },
        ];
        returns.forEach((r) => {
          cy.request({
            method: 'POST',
            url: `/api/v1/admin/products/${productCode}/returns`,
            body: r,
            headers,
          });
        });
        cy.request({
          method: 'PATCH',
          url: `/api/v1/admin/products/${productCode}/status`,
          body: { status: 'active' },
          headers,
        });
      });
    });
  });
});

// Custom command: seed questions via API (idempotent - skips if questions exist)
Cypress.Commands.add('seedQuestions', () => {
  cy.request('POST', '/api/v1/auth/admin/login', {
    username: 'admin',
    password: 'admin123',
  }).then((loginResp) => {
    const token = loginResp.body.access_token;
    const headers = { Authorization: `Bearer ${token}` };

    // Check if questions already exist
    cy.request({ method: 'GET', url: '/api/v1/admin/questions', headers }).then((resp) => {
      if (resp.body.length > 0) {
        // Questions already seeded
        return;
      }

      const questions = [
        {
          content: '您的年龄段是？',
          sort_order: 1,
          options: [
            { content: '25岁以下', score: 5 },
            { content: '25-35岁', score: 4 },
            { content: '35-50岁', score: 3 },
            { content: '50-60岁', score: 2 },
            { content: '60岁以上', score: 1 },
          ],
        },
        {
          content: '您的投资经验？',
          sort_order: 2,
          options: [
            { content: '无经验', score: 1 },
            { content: '1-3年', score: 3 },
            { content: '3年以上', score: 5 },
          ],
        },
      ];

      questions.forEach((q) => {
        cy.request({ method: 'POST', url: '/api/v1/admin/questions', body: q, headers });
      });
    });
  });
});

declare global {
  namespace Cypress {
    interface Chainable {
      adminLogin(username?: string, password?: string): Chainable<void>;
      createAnonymousCustomer(): Chainable<void>;
      seedProduct(productCode: string, name: string): Chainable<void>;
      seedQuestions(): Chainable<void>;
    }
  }
}
