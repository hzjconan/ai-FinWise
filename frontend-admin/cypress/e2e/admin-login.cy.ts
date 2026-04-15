describe('Admin Login', () => {
  beforeEach(() => {
    cy.visit('/login');
  });

  it('shows login form', () => {
    cy.contains('FinWise 管理后台');
    cy.get('input[id="username"]').should('be.visible');
    cy.get('input[id="password"]').should('be.visible');
  });

  it('logs in with valid credentials', () => {
    cy.get('input[id="username"]').type('admin');
    cy.get('input[id="password"]').type('admin123');
    cy.get('button[type="submit"]').click();
    cy.url().should('include', '/dashboard');
  });

  it('rejects invalid credentials', () => {
    cy.get('input[id="username"]').type('admin');
    cy.get('input[id="password"]').type('wrongpass');
    cy.get('button[type="submit"]').click();
    // Should stay on login page (not navigate to dashboard)
    cy.url().should('include', '/login');
    cy.url().should('not.include', '/dashboard');
  });

  it('redirects unauthenticated users to login', () => {
    cy.visit('/products');
    cy.url().should('include', '/login');
  });
});
