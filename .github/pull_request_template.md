# Pull Request

## Description
<!-- Provide a brief description of the changes in this PR -->

## Type of Change
<!-- Mark the relevant option with an [x] -->
- [ ] 🐛 Bug fix (non-breaking change that fixes an issue)
- [ ] ✨ New feature (non-breaking change that adds functionality)
- [ ] 💥 Breaking change (fix or feature that would cause existing functionality to change)
- [ ] 📝 Documentation update
- [ ] 🔧 Infrastructure/Configuration
- [ ] 🧹 Code cleanup/refactor
- [ ] ⚡ Performance improvement
- [ ] 🧪 Test addition/update

## Related Issues
<!-- Link any related issues here using #issue_number -->
- Fixes #

## Changes Made
<!-- List the main changes made in this PR -->
1. 
2. 
3. 

## Testing Done
<!-- Describe the testing that was done to verify these changes -->
- [ ] Unit tests pass (`pytest`)
- [ ] Lint checks pass (`flake8`)
- [ ] Integration tests pass
- [ ] Manual testing performed

### Test Commands Run
```bash
# Example commands
pytest
flake8
terraform validate
```

## Checklist
<!-- Mark completed items with an [x] -->
- [ ] My code follows the project's style guidelines
- [ ] I have performed a self-review of my code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings
- [ ] I have updated tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes
- [ ] Any dependent changes have been merged and published

## Infrastructure Changes (if applicable)
<!-- If this PR includes Terraform/infrastructure changes -->
- [ ] Terraform plan generated and reviewed
- [ ] No unexpected resource changes
- [ ] State file will be updated

### Terraform Validation
```bash
cd infra/environments/dev
terraform validate
terraform plan
```

## Data Pipeline Impact (if applicable)
<!-- If this PR affects the data pipeline -->
- [ ] Bronze layer schema unchanged
- [ ] Silver layer schema unchanged
- [ ] ETL logic updated
- [ ] Data validation rules updated

## Screenshots/Logs (if applicable)
<!-- Add screenshots or logs that help explain your changes -->

## Additional Notes
<!-- Any other information that would be helpful to reviewers -->

## Deployment Notes
<!-- Any special deployment instructions or considerations -->

---

**Reviewers**: Please check the following:
- [ ] Code quality and logic
- [ ] Test coverage
- [ ] Documentation completeness
- [ ] Infrastructure safety
- [ ] Breaking changes identified